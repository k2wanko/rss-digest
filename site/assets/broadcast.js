(() => {
  const root = document.querySelector("[data-broadcast]");
  if (!root || !("speechSynthesis" in window)) {
    return;
  }

  const button = root.querySelector(".broadcast-play");
  const script = root.querySelector(".broadcast-script");
  if (!button || !script) {
    return;
  }

  const text = script.textContent.replace(/\s+/g, " ").trim();
  if (!text) {
    return;
  }

  button.hidden = false;

  let keepAlive = 0;

  const setLabel = (label) => {
    button.textContent = label;
  };

  const stopKeepAlive = () => {
    if (keepAlive) {
      clearInterval(keepAlive);
      keepAlive = 0;
    }
  };

  const startKeepAlive = () => {
    stopKeepAlive();
    keepAlive = window.setInterval(() => {
      if (speechSynthesis.speaking && !speechSynthesis.paused) {
        speechSynthesis.pause();
        speechSynthesis.resume();
      }
    }, 12000);
  };

  const pickVoice = () => {
    const voices = speechSynthesis.getVoices();
    return (
      voices.find((voice) => voice.lang === "ja-JP") ||
      voices.find((voice) => voice.lang.startsWith("ja")) ||
      null
    );
  };

  const reset = () => {
    stopKeepAlive();
    setLabel("読み上げる");
  };

  const speak = () => {
    speechSynthesis.cancel();
    const utterance = new SpeechSynthesisUtterance(text);
    utterance.lang = "ja-JP";
    utterance.rate = 1;
    const voice = pickVoice();
    if (voice) {
      utterance.voice = voice;
    }
    utterance.onend = reset;
    utterance.onerror = reset;
    speechSynthesis.speak(utterance);
    startKeepAlive();
    setLabel("一時停止");
  };

  button.addEventListener("click", () => {
    if (speechSynthesis.paused) {
      speechSynthesis.resume();
      startKeepAlive();
      setLabel("一時停止");
      return;
    }
    if (speechSynthesis.speaking) {
      speechSynthesis.pause();
      stopKeepAlive();
      setLabel("続きから");
      return;
    }
    speak();
  });

  document.addEventListener("visibilitychange", () => {
    if (document.hidden && speechSynthesis.speaking) {
      speechSynthesis.cancel();
      reset();
    }
  });
})();
