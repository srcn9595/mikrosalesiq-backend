<#-- login.ftl -->
<!DOCTYPE html>
<html lang="tr">
<head>
  <meta charset="UTF-8" />
  <title>MikrogrupIQ Giriş</title>
  <link rel="stylesheet" href="${url.resourcesPath}/css/styles.css" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
</head>
<body>

  <div class="login-wrapper">
    <div class="login-box">
      <div class="login-header">
        <img src="${url.resourcesPath}/img/mikrogrup.svg" alt="MikrogrupIQ Logo" class="logo" />
        <h1>MikrogrupIQ</h1>
        <p class="subtitle">Kurumsal Asistan Platformuna Giriş Yapın</p>
      </div>

      <#-- Keycloak'ın varsayılan form alanı -->
      <#include "login-form.ftl">

      <div class="footer">
        <p>&copy; 2025 Mikrogrup Teknoloji A.Ş.</p>
      </div>
    </div>
  </div>

</body>
</html>
