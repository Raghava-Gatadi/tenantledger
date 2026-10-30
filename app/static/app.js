"use strict";
const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
const escape = (value) => String(value ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const money = cents => new Intl.NumberFormat("en-US", {style:"currency", currency:"USD"}).format(cents / 100);
const date = value => new Date(value).toLocaleDateString("en-US", {month:"short", day:"numeric", year:"numeric"});
const initials = name => name.split(" ").map(n => n[0]).slice(0,2).join("");
const statusName = status => ({draft:"Draft",submitted:"Pending",approved:"Approved",rejected:"Rejected"}[status]);
const badge = status => `<span class="badge ${escape(status)}">${statusName(status)}</span>`;
const state = {user:null, org:null, view:"expenses", filter:"", q:"", offset:0, auditOffset:0, load:0};
let toastTimer;
function toast(message, error = false) {
  const el = $("#toast"); el.textContent = message; el.classList.toggle("error", error); el.hidden = false;
  clearTimeout(toastTimer); toastTimer = setTimeout(() => el.hidden = true, 5500);
}
function run(action) { return async event => { try { await action(event); } catch (error) { toast(error.message, true); } }; }
async function api(path, options = {}) {
  const headers = new Headers(options.headers || {});
  if (options.body && !(options.body instanceof FormData)) headers.set("Content-Type", "application/json");
  if (state.user?.csrf_token) headers.set("X-CSRF-Token", state.user.csrf_token);
  const response = await fetch(path, {...options, headers, credentials:"same-origin"});
  if (!response.ok) {
    let detail; try { detail = (await response.json()).detail; } catch { detail = "Request failed"; }
    if (response.status === 401 && path !== "/api/me") {
      $("#modal").close(); $("#workspace").hidden = true; $("#welcome").hidden = false;
    }
    throw new Error(Array.isArray(detail) ? detail.map(d => `${d.loc.at(-1)}: ${d.msg}`).join("; ") : detail || "Request failed");
  }
  return options.raw ? response : response.json();
}
const orgPath = suffix => `/api/orgs/${encodeURIComponent(state.org.id)}${suffix}`;
function modal(title, html, eyebrow = "TENANTLEDGER") {
  $("#modal-title").textContent = title; $("#modal-eyebrow").textContent = eyebrow;
  $("#modal-body").innerHTML = html;
  if (!$("#modal").open) $("#modal").showModal();
}
function bindForm(id, handler) {
  $(id).addEventListener("submit", async event => {
    event.preventDefault(); const button = $("[type=submit]", event.currentTarget); button.disabled = true;
    const errorEl = $(".form-error", event.currentTarget); if (errorEl) errorEl.textContent = "";
    try { await handler(new FormData(event.currentTarget)); }
    catch (error) { if (errorEl) errorEl.textContent = error.message; else toast(error.message, true); }
    finally { button.disabled = false; }
  });
}
async function boot() {
  try { state.user = await api("/api/me"); }
  catch (error) {
    $("#loading").hidden = true; $("#welcome").hidden = false;
    if (!error.message.includes("Sign in")) toast(error.message, true);
    return;
  }
  $("#loading").hidden = true; $("#welcome").hidden = true; $("#workspace").hidden = false;
  $("#user-name").textContent = state.user.name; $("#user-email").textContent = state.user.email;
  $("#avatar").textContent = initials(state.user.name);
  $("#organization").innerHTML = state.user.organizations.map(o => `<option value="${escape(o.id)}">${escape(o.name)}</option>`).join("");
  state.org = state.user.organizations.find(o => o.id === sessionStorage.getItem("ledger-org")) || state.user.organizations[0];
  $("#empty-org").hidden = !!state.org; $("#expense-view").hidden = !state.org;
  if (state.org) { $("#organization").value = state.org.id; await chooseOrg(); }
  else { $$(".nav-item").forEach(n => n.hidden = true); $("#role-label").textContent = "No active memberships"; }
}
async function chooseOrg() {
  state.org = state.user.organizations.find(o => o.id === $("#organization").value);
  sessionStorage.setItem("ledger-org", state.org.id); state.offset = 0; state.auditOffset = 0;
  $("#modal").close(); $("#role-label").textContent = state.org.role + " access";
  $$(".nav-item").forEach(n => n.hidden = !({expenses:true,members:["admin","auditor"].includes(state.org.role),audit:["admin","auditor"].includes(state.org.role),assignments:state.org.role === "admin"}[n.dataset.view]));
  $("#new-expense").hidden = !["employee","approver"].includes(state.org.role);
  $("#invite-member").hidden = state.org.role !== "admin";
  $("#expense-title").textContent = state.org.role === "auditor" ? "Organization expenses" : state.org.role === "approver" ? "Expenses & approvals" : "Your expenses";
  $("#expense-subtitle").textContent = state.org.role === "admin" ? "Administrative access manages people and assignments. Expense access follows ownership." : "From the first receipt to the final approval.";
  await showView(state.org.role === "admin" ? "members" : "expenses");
}
async function showView(view) {
  state.view = view;
  for (const name of ["expenses","members","audit","assignments"]) $(`#${name === "expenses" ? "expense" : name}-view`).hidden = name !== view;
  $$(".nav-item").forEach(n => n.classList.toggle("active", n.dataset.view === view));
  $("#breadcrumb-current").textContent = {expenses:"Expenses",members:"Team members",audit:"Activity log",assignments:"Assignments"}[view];
  await ({expenses:loadExpenses,members:loadMembers,audit:loadAudit,assignments:loadAssignments}[view])();
}
async function loadExpenses() {
  const generation = ++state.load;
  const params = new URLSearchParams({limit:10,offset:state.offset,q:state.q}); if (state.filter) params.set("status",state.filter);
  const [list, summary] = await Promise.all([api(orgPath(`/expenses?${params}`)),api(orgPath("/summary"))]);
  if (generation !== state.load) return;
  const total = Object.values(summary).reduce((n,s) => n + s.amount_cents,0);
  const count = Object.values(summary).reduce((n,s) => n + s.count,0);
  $("#nav-count").textContent = count;
  const stats = [
    ["Total expenses",money(total),`${count} expenses visible to you`,"↗"],
    ["Awaiting approval",money(summary.submitted.amount_cents),`${summary.submitted.count} pending review`,"◷"],
    ["Approved",money(summary.approved.amount_cents),`${summary.approved.count} approved expenses`,"✓"],
    ["Draft expenses",String(summary.draft.count),"Ready when you are","▤"],
  ];
  $("#stats").innerHTML = stats.map(([label,value,foot,icon]) => `<article class="stat"><span class="stat-label">${label}<span class="stat-icon">${icon}</span></span><strong class="stat-value">${value}</strong><span class="stat-foot">${foot}</span></article>`).join("");
  $("#total-count").textContent = list.total;
  const icons = {Travel:"↗",Meals:"♧",Software:"▦",Office:"▧",Other:"◇"};
  $("#expense-rows").innerHTML = list.items.map(e => `<tr><td><div class="expense-cell"><span class="category-icon">${icons[e.category] || "◇"}</span><div><button class="expense-link" data-expense="${e.id}">${escape(e.title)}</button><span class="expense-category">${escape(e.category)}</span></div></div></td><td>${escape(e.owner_name)}</td><td>${date(e.created_at)}</td><td class="amount">${money(e.amount_cents)}</td><td>${badge(e.status)}</td><td><button class="row-arrow" data-expense="${e.id}" aria-label="Open ${escape(e.title)}">↗</button></td></tr>`).join("");
  $("#table-empty").hidden = list.items.length > 0;
  $("#page-info").textContent = list.total ? `Showing ${state.offset + 1}–${state.offset + list.items.length} of ${list.total} expenses` : "0 expenses";
  $("#prev-page").disabled = state.offset === 0; $("#next-page").disabled = state.offset + list.items.length >= list.total;
  $$("[data-expense]").forEach(el => el.addEventListener("click",run(() => openExpense(el.dataset.expense))));
}
function expenseForm(existing = null) {
  modal(existing ? "Edit draft" : "New expense", `<form id="expense-form"><label class="field">Expense title<input name="title" required maxlength="120" placeholder="e.g. Client workshop train tickets" value="${escape(existing?.title || "")}"></label><div class="field-row"><label class="field">Amount (USD)<input name="amount" type="number" min="0.01" max="1000000" step="0.01" required placeholder="0.00" value="${existing ? (existing.amount_cents / 100).toFixed(2) : ""}"></label><label class="field">Category<select name="category" aria-label="Category">${["Travel","Meals","Software","Office","Other"].map(c => `<option${existing?.category === c ? " selected" : ""}>${c}</option>`).join("")}</select></label></div><label class="field">Note <span class="helper">(optional)</span><textarea name="note" maxlength="2000" placeholder="Add some context for your approver">${escape(existing?.note || "")}</textarea></label><p class="helper">Saved as a draft. Add receipts and choose an approver before submitting.</p><p class="form-error" role="alert"></p><div class="form-actions"><button type="button" class="button secondary" id="cancel-form">Cancel</button><button type="submit" class="button primary">${existing ? "Save changes" : "Create draft"}</button></div></form>`,state.org.name);
  $("#cancel-form").onclick = () => $("#modal").close();
  bindForm("#expense-form", async form => {
    const body = {title:form.get("title"),amount_cents:Math.round(Number(form.get("amount")) * 100),category:form.get("category"),note:form.get("note")};
    if (existing) body.version = existing.version;
    const result = await api(orgPath("/expenses" + (existing ? `/${existing.id}` : "")), {method:existing ? "PATCH" : "POST",body:JSON.stringify(body)});
    toast(existing ? "Draft updated" : "Expense draft created"); await loadExpenses(); await openExpense(result.id);
  });
}
async function openExpense(id) {
  const e = await api(orgPath(`/expenses/${id}`));
  const editable = e.owner_id === state.user.id && e.status === "draft" && ["employee","approver"].includes(state.org.role);
  const decidable = state.org.role === "approver" && e.status === "submitted" && e.approver_id === state.user.id && e.owner_id !== state.user.id;
  modal(e.title, `${badge(e.status)}<div class="detail-amount">${money(e.amount_cents)}</div><dl class="detail-grid"><div><dt>Submitted by</dt><dd>${escape(e.owner_name)}</dd></div><div><dt>Category</dt><dd>${escape(e.category)}</dd></div><div><dt>Created</dt><dd>${date(e.created_at)}</dd></div><div><dt>Approver</dt><dd>${escape(e.approver_name || "Not assigned yet")}</dd></div></dl>${e.note ? `<p class="detail-note">${escape(e.note)}</p>` : ""}<div class="receipt-list"><h3>Receipts</h3>${e.receipts.length ? e.receipts.map(r => `<a href="${orgPath(`/expenses/${id}/receipts/${r.id}`)}" download>↓ &nbsp; ${escape(r.filename)}</a>`).join("") : '<p class="helper">No receipts attached.</p>'}${editable ? '<label>Add a receipt · PDF, PNG or JPEG · up to 2 MB<input id="receipt-file" type="file" accept=".pdf,.png,.jpg,.jpeg"></label>' : ""}</div><div class="form-actions">${editable ? '<button class="button secondary" id="edit-draft">Edit draft</button><button class="button primary" id="submit-expense">Submit for approval →</button>' : ""}${decidable ? '<button class="button danger" id="reject-expense">Reject</button><button class="button primary" id="approve-expense">✓ Approve expense</button>' : ""}</div>`,state.org.name);
  if (editable) {
    $("#edit-draft").onclick = () => expenseForm(e);
    $("#receipt-file").addEventListener("change",run(async event => {
      const file = event.target.files[0]; if (!file) return;
      if (file.size > 2000000) throw new Error("Receipt must be 2 MB or smaller");
      const form = new FormData(); form.append("file", file);
      await api(orgPath(`/expenses/${id}/receipts`), {method:"POST",body:form}); toast("Receipt attached"); await openExpense(id);
    }));
    $("#submit-expense").onclick = run(async () => {
      const approvers = await api(orgPath("/approvers"));
      modal("Choose an approver", `<form id="submit-form"><p class="helper">Once submitted, this expense cannot be edited.</p><label class="field">Approver<select name="approver" aria-label="Approver" required>${approvers.map(a => `<option value="${a.id}">${escape(a.name)}</option>`).join("")}</select></label>${!approvers.length ? '<p class="form-error">No eligible approver. Ask your organization admin to assign one.</p>' : ""}<p class="form-error" role="alert"></p><div class="form-actions"><button type="submit" class="button primary" ${!approvers.length ? "disabled" : ""}>Submit expense</button></div></form>`);
      bindForm("#submit-form", async form => { await api(orgPath(`/expenses/${id}/submit`),{method:"POST",body:JSON.stringify({approver_id:form.get("approver"),version:e.version})}); $("#modal").close(); toast("Expense submitted for approval"); await loadExpenses(); });
    });
  }
  if (decidable) {
    const decide = async (decision, reason = "") => { await api(orgPath(`/expenses/${id}/decision`), {method:"POST",body:JSON.stringify({decision,reason,version:e.version})}); $("#modal").close(); toast(`Expense ${decision}`); await loadExpenses(); };
    $("#approve-expense").onclick = run(() => decide("approved"));
    $("#reject-expense").onclick = () => {
      modal("Reject expense", '<form id="reject-form"><label class="field">Reason<textarea name="reason" required maxlength="500" placeholder="Explain what needs to change"></textarea></label><p class="form-error" role="alert"></p><div class="form-actions"><button class="button danger" type="submit">Reject expense</button></div></form>');
      bindForm("#reject-form", form => decide("rejected", form.get("reason")));
    };
  }
}
async function loadMembers() {
  const members = await api(orgPath("/members")); const admin = state.org.role === "admin";
  $("#member-list").innerHTML = members.map(m => `<div class="member-card" data-member="${m.id}"><span class="avatar">${escape(initials(m.name))}</span><div class="member-info"><strong>${escape(m.name)}${m.id === state.user.id ? ' <small>(you)</small>' : ""}</strong><small>${escape(m.email)}</small></div><select aria-label="Role for ${escape(m.name)}" ${admin ? "" : "disabled"}>${["employee","approver","admin","auditor"].map(r => `<option value="${r}" ${m.role === r ? "selected" : ""}>${r[0].toUpperCase()+r.slice(1)}</option>`).join("")}</select><label><input type="checkbox" ${m.active ? "checked" : ""} ${admin ? "" : "disabled"}> Active</label>${admin ? '<button class="button secondary save-member">Save</button>' : ""}</div>`).join("");
  $$(".save-member").forEach(btn => btn.onclick = run(async () => {
    const row = btn.closest("[data-member]"); btn.disabled = true;
    try { await api(orgPath(`/members/${row.dataset.member}`),{method:"PATCH",body:JSON.stringify({role:$("select",row).value,active:$("input",row).checked})}); toast("Membership updated"); if (row.dataset.member === state.user.id) await boot(); else await loadMembers(); }
    finally { btn.disabled = false; }
  }));
}
function inviteMember() {
  modal("Invite a teammate", '<form id="invite-form"><label class="field">Email address<input name="email" type="email" required placeholder="teammate@example.test"></label><label class="field">Organization role<select name="role"><option>employee</option><option>approver</option><option>admin</option><option>auditor</option></select></label><p class="helper">The invitation can be accepted only by the account with this verified email address. You’ll receive a token to share; this demo does not send email.</p><p class="form-error" role="alert"></p><div class="form-actions"><button class="button primary" type="submit">Create invitation</button></div></form>');
  bindForm("#invite-form", async form => {
    const result = await api(orgPath("/invitations"),{method:"POST",body:JSON.stringify({email:form.get("email"),role:form.get("role")})});
    modal("Invitation ready", `<p class="helper">Share this single-use token with your teammate. It expires in 24 hours. They can select “Accept an invitation” after signing in.</p><div class="token-box" id="invitation-token">${escape(result.token)}</div><button class="button primary" id="copy-token">Copy token</button>`);
    $("#copy-token").onclick = run(async () => { await navigator.clipboard.writeText(result.token); toast("Invitation token copied"); });
  });
}
function acceptInvitation() {
  modal("Join an organization", '<form id="accept-form"><label class="field">Invitation token<input name="token" required minlength="32" maxlength="100" autocomplete="off"></label><p class="helper">Use the token shared by your organization admin.</p><p class="form-error" role="alert"></p><div class="form-actions"><button class="button primary" type="submit">Accept invitation</button></div></form>');
  bindForm("#accept-form", async form => { await api("/api/invitations/accept",{method:"POST",body:JSON.stringify({token:form.get("token")})}); $("#modal").close(); toast("You’ve joined the organization"); await boot(); });
}
async function loadAudit() {
  const rows = await api(orgPath(`/audit?limit=20&offset=${state.auditOffset}`));
  $("#audit-list").innerHTML = rows.length ? rows.map(e => `<article class="audit-event"><span class="event-icon">✓</span><div><strong>${escape(e.action.replaceAll("."," · "))}</strong><small>Actor ${escape(e.actor_id)}<br>Record ${escape(e.object_id)}</small>${Object.keys(e.detail).length ? `<pre>${escape(JSON.stringify(e.detail,null,2))}</pre>` : ""}</div><time>${date(e.created_at)}</time></article>`).join("") : '<div class="empty-state"><h3>No activity on this page</h3></div>';
  $("#audit-page-info").textContent = rows.length ? `Events ${state.auditOffset+1}–${state.auditOffset+rows.length}` : "No events";
  $("#audit-prev").disabled = state.auditOffset === 0; $("#audit-next").disabled = rows.length < 20;
}
async function loadAssignments() {
  const [rows,approvers] = await Promise.all([api(orgPath("/assignments")),api(orgPath("/approvers"))]);
  $("#assignment-list").innerHTML = rows.length ? rows.map(e => `<div class="member-card" data-assignment="${e.id}" data-version="${e.version}"><span class="avatar">⇄</span><div class="member-info"><strong>Pending expense</strong><small>${escape(e.id)}</small></div><select aria-label="Assigned approver">${approvers.filter(a => a.id !== e.owner_id).map(a => `<option value="${a.id}" ${e.approver_id === a.id ? "selected" : ""}>${escape(a.name)}</option>`).join("")}</select><button class="button secondary save-assignment">Reassign</button></div>`).join("") : '<div class="empty-state"><h3>No pending assignments</h3></div>';
  $$(".save-assignment").forEach(btn => btn.onclick = run(async () => { const row = btn.closest("[data-assignment]"); await api(orgPath(`/expenses/${row.dataset.assignment}/assignment`),{method:"POST",body:JSON.stringify({approver_id:$("select",row).value,version:Number(row.dataset.version)})}); toast("Approver reassigned"); await loadAssignments(); }));
}
$("#organization").addEventListener("change",run(chooseOrg));
$$(".nav-item").forEach(btn => btn.onclick = run(() => showView(btn.dataset.view)));
$("#close-modal").onclick = () => $("#modal").close();
$("#new-expense").onclick = () => expenseForm();
$("#invite-member").onclick = inviteMember;
$("#accept-invite").onclick = acceptInvitation; $("#join-org").onclick = acceptInvitation;
$("#refresh-audit").onclick = run(loadAudit);
$("#audit-prev").onclick = run(async () => { state.auditOffset = Math.max(0,state.auditOffset-20); await loadAudit(); });
$("#audit-next").onclick = run(async () => { state.auditOffset += 20; await loadAudit(); });
$("#prev-page").onclick = run(async () => { state.offset = Math.max(0,state.offset-10); await loadExpenses(); });
$("#next-page").onclick = run(async () => { state.offset += 10; await loadExpenses(); });
$$("#filters button").forEach(btn => btn.onclick = run(async () => {
  state.filter = btn.dataset.status; state.offset = 0;
  $$("#filters button").forEach(b => b.classList.toggle("selected",b === btn)); await loadExpenses();
}));
let searchTimer;
$("#search").addEventListener("input",() => { clearTimeout(searchTimer); searchTimer = setTimeout(run(async () => { state.q = $("#search").value; state.offset = 0; await loadExpenses(); }),250); });
$("#export").onclick = run(async () => {
  const response = await api(orgPath("/expenses/export"),{raw:true}); const url = URL.createObjectURL(await response.blob());
  const a = document.createElement("a"); a.href = url; a.download = "expenses.csv"; a.click(); setTimeout(() => URL.revokeObjectURL(url),1000); toast("Your expense export is ready");
});
$("#logout").onclick = run(async () => { const result = await api("/auth/logout",{method:"POST"}); location.assign(result.redirect); });
$("#mobile-logout").onclick = $("#logout").onclick;
boot().catch(error => toast(error.message,true));
