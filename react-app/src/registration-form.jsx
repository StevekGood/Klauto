import { useState } from "react";

export default function RegistrationForm({ onSubmit }) {
  const [regUserIdInput, setRegUserIdInput] = useState("");
  const [regAuthKeyInput, setRegAuthKeyInput] = useState("");

  return (
    <div className="main">
      <h2>Klauto</h2>
      <br />
      <h3>Регистрация</h3>
      <br />
      <div className="form-container">
        <form
          onSubmit={(e) => {
            e.preventDefault();
            onSubmit(regUserIdInput, regAuthKeyInput);
          }}
        >
          <div className="reg-form-table-container">
            <div className="reg-form-table-group">
              <label htmlFor="reg-user-id-input">ID Пользователя</label>
              <input
                id="reg-user-id-input"
                type="number"
                name="user-id"
                maxLength="16"
                value={regUserIdInput}
                onChange={(e) => setRegUserIdInput(e.target.value)}
              />
            </div>
            <div className="reg-form-table-group">
              <label htmlFor="reg-user-auth-input">Auth ключ</label>
              <input
                id="reg-user-auth-input"
                type="text"
                name="user-auth-key"
                maxLength="64"
                spellCheck="false"
                value={regAuthKeyInput}
                onChange={(e) => setRegAuthKeyInput(e.target.value)}
              />
            </div>
          </div>
          <div className="reg-form-flex-group">
            <button type="submit">Зарегистрироваться</button>
          </div>
        </form>
      </div>
    </div>
  );
}
