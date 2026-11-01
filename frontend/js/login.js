const form = document.getElementById("login-form");
const flash = document.getElementById("flash");

SZI.me()
  .then((user) => {
    window.location.replace(user.role === "admin" ? "/admin" : "/denied");
  })
  .catch(() => {});

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  flash.classList.remove("show");
  try {
    const user = await SZI.login(
      document.getElementById("login").value,
      document.getElementById("password").value,
    );
    window.location.replace(user.role === "admin" ? "/admin" : "/denied");
  } catch (err) {
    flash.textContent = err.message;
    flash.classList.add("show");
  }
});
