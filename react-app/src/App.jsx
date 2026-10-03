import { useState, useEffect, useRef } from "react";
import "./App.css";
import RegistrationForm from "./registration-form";
import PageLoading from "./page-loading";

function App() {
  const [isAuth, setIsAuth] = useState(false);
  const [loading, setLoading] = useState(true);

  const isAuthRequestSent = useRef(false);

  async function checkUserAuth() {
    const rawInitData =
      window.Telegram?.WebApp?.initData || "missing_telegram_init_data";

    try {
      const response = await fetch("https://klauto.onrender.com/auth", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `tma ${rawInitData}`,
        },
      });
      if (response.ok) {
        const data = await response.json();
        setIsAuth(data.isAuth === true);
      }
    } catch (error) {
      console.error(error);
      setIsAuth(false);
    } finally {
      setLoading(false);
    }
  }

  async function handleRegister(userId, authKey) {
    if (isAuth) return;
    if (!userId || !authKey) {
      alert("Пожалуйста, заполните все поля формы.");
      return;
    }

    setLoading(true);
    const rawInitData =
      window.Telegram?.WebApp?.initData || "missing_telegram_init_data";

    try {
      const response = await fetch("https://klauto.onrender.com/register", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `tma ${rawInitData}`,
        },
        body: JSON.stringify({
          userId: userId,
          authKey: authKey,
        }),
      });

      if (response.ok) {
        const data = await response.json();
        setIsAuth(data.isAuth === true);
      } else {
        const errorData = await response.json();
        alert(`Ошибка регистрации: ${errorData.detail}`);
      }
    } catch (error) {
      console.error(error);
      alert("Ошибка: не удалось связаться с сервером.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    if (isAuthRequestSent.current) return;
    isAuthRequestSent.current = true;
    if (window.Telegram?.WebApp) {
      window.Telegram.WebApp.ready();
      window.Telegram.WebApp.expand();
    }
    checkUserAuth();
  }, []);

  let content;
  if (loading) {
    content = <PageLoading />;
  } else if (!isAuth) {
    content = <RegistrationForm onSubmit={handleRegister} />;
  }

  return <div className="main">{content}</div>;
}

export default App;
