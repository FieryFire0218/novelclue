(() => {
  const input = document.getElementById("guessInput");
  const source = document.getElementById("novelOptions");
  if (!input || !source) return;

  const titles = [...source.options].map(option => option.value);
  const normalize = value => value.normalize("NFKC").toLowerCase().trim();

  // disable the browser's dropdown, retain its options as data source
  input.removeAttribute("list");
  input.setAttribute("autocomplete", "off");
  input.setAttribute("autocapitalize", "none");
  input.spellcheck = false;

  const wrapper = document.createElement("div");
  wrapper.className = "novel-picker";
  input.before(wrapper);
  wrapper.append(input);

  const suggestions = document.createElement("div");
  suggestions.className = "novel-suggestions";
  suggestions.id = "novelSuggestions";
  suggestions.setAttribute("role", "group");
  suggestions.setAttribute("aria-label", "Matching novel titles");
  suggestions.hidden = true;
  wrapper.append(suggestions);

  input.setAttribute("aria-controls", suggestions.id);

  function closeSuggestions() {
    suggestions.hidden = true;
  }

  function showSuggestions() {
    if (input.disabled) {
      closeSuggestions();
      return;
    }

    const query = normalize(input.value);
    const matches = titles
      .filter(title => !query || normalize(title).includes(query))
      .slice(0, 20);

    suggestions.replaceChildren();

    for (const title of matches) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "novel-suggestion";
      button.textContent = title;

      button.addEventListener("click", () => {
        input.value = title;
        input.focus();
        closeSuggestions();
      });

      suggestions.append(button);
    }

    if (!matches.length) {
      const message = document.createElement("p");
      message.className = "novel-search-note";
      message.textContent = "No matching titles. Try another spelling.";
      suggestions.append(message);
    }

    suggestions.hidden = false;
  }

  input.addEventListener("input", showSuggestions);
  input.addEventListener("focus", showSuggestions);
  input.addEventListener("click", showSuggestions);

  input.addEventListener("keydown", event => {
    if (event.isComposing) return;

    if (event.key === "ArrowDown") {
      event.preventDefault();
      showSuggestions();
      suggestions.querySelector("button")?.focus();
    } else if (event.key === "Escape") {
      closeSuggestions();
    }
  });

  suggestions.addEventListener("keydown", event => {
    const buttons = [...suggestions.querySelectorAll("button")];
    const index = buttons.indexOf(document.activeElement);

    if (event.key === "Escape") {
      input.focus();
      closeSuggestions();
    } else if (event.key === "ArrowDown") {
      event.preventDefault();
      buttons[Math.min(index + 1, buttons.length - 1)]?.focus();
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      if (index <= 0) input.focus();
      else buttons[index - 1].focus();
    }
  });

  wrapper.addEventListener("focusout", event => {
    if (!wrapper.contains(event.relatedTarget)) closeSuggestions();
  });

  document.addEventListener("pointerdown", event => {
    if (!wrapper.contains(event.target)) closeSuggestions();
  });

  input.form.addEventListener("submit", closeSuggestions, true);
  document.getElementById("resetBtn")
    ?.addEventListener("click", closeSuggestions);
})();