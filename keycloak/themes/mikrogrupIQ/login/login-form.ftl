<#-- login-form.ftl -->

<style>
  body {
    background-color: #fafafa;
    font-family: 'Segoe UI', Tahoma, sans-serif;
    margin: 0;
    padding: 0;
  }

  .login-container {
    display: flex;
    align-items: center;
    justify-content: center;
    min-height: 100vh;
  }

  .login-box {
    background-color: white;
    border: 1px solid #e5e7eb;
    border-radius: 8px;
    padding: 32px;
    width: 100%;
    max-width: 400px;
    text-align: center;
    box-shadow: 0 2px 8px rgba(0,0,0,0.05);
  }

  .logo {
    width: 38px;
    margin-bottom: 24px;
  }

  h2 {
    font-size: 20px;
    font-weight: 600;
    margin-bottom: 12px;
    color: #111827;
  }

  form {
    margin-top: 12px;
    text-align: left;
  }

  label {
    display: block;
    font-size: 14px;
    font-weight: 500;
    margin-bottom: 6px;
    color: #374151;
  }

  input[type="text"],
  input[type="password"] {
    width: 100%;
    padding: 10px 14px;
    margin-bottom: 16px;
    border: 1px solid #d1d5db;
    border-radius: 6px;
    font-size: 14px;
  }

  input[type="submit"] {
    width: 100%;
    background-color: #111827;
    color: white;
    border: none;
    padding: 12px;
    font-weight: 600;
    font-size: 15px;
    border-radius: 6px;
    cursor: pointer;
    margin-top: 8px;
  }

  input[type="submit"]:hover {
    background-color: #000000;
  }

  .footer {
    margin-top: 20px;
    font-size: 12px;
    color: #6b7280;
  }

  .footer a {
    color: #2563eb;
    text-decoration: none;
  }

  .footer a:hover {
    text-decoration: underline;
  }
</style>

<div class="login-container">
  <div class="login-box">
    <img class="logo" src="${url.resourcesPath}/img/mikrogrup.svg" alt="MikrogrupIQ" />
    <h2>Welcome back</h2>

    <form id="kc-form-login" action="${url.loginAction}" method="post">
      <label for="username">${msg("username")}</label>
      <input id="username" name="username" type="text" value="${(login.username!'')}" autofocus autocomplete="username" />

      <label for="password">${msg("password")}</label>
      <input id="password" name="password" type="password" autocomplete="current-password" />

      <input type="submit" id="kc-login" name="login" value="${msg("doLogIn")}" />
    </form>

    <div class="footer">
      <a href="${url.loginResetCredentialsUrl}">${msg("doForgotPassword")}</a>
    </div>
  </div>
</div>
