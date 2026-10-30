"use strict";
window.addEventListener("load", () => {
  window.SwaggerUIBundle({url:"/openapi.json",dom_id:"#swagger-ui",deepLinking:true,persistAuthorization:false,validatorUrl:null});
});
