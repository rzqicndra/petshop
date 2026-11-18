"use strict";
// Progressive enhancement: real selects remain the source of values and validation.
(() => {
  let current = null,
    counter = 0;
  function enhance(select) {
    if (select.dataset.enhanced || (select.size > 1 && !select.multiple))
      return;
    select.dataset.enhanced = "true";
    const id = `choice-${++counter}`,
      wrap = document.createElement("div"),
      trigger = document.createElement("button"),
      popup = document.createElement("div"),
      list = document.createElement("div"),
      search = document.createElement("input");
    wrap.className = "choice";
    select.before(wrap);
    wrap.append(select, trigger, popup);
    select.classList.add("enhanced-select");
    select.tabIndex = -1;
    select.setAttribute("aria-hidden", "true");
    trigger.type = "button";
    trigger.className = "choice-trigger";
    trigger.id = id;
    trigger.setAttribute("role", "combobox");
    trigger.setAttribute("aria-haspopup", "listbox");
    trigger.setAttribute("aria-expanded", "false");
    trigger.setAttribute("aria-controls", id + "-list");
    const label = select.labels?.[0];
    if (label) {
      if (!label.id) label.id = id + "-label";
      trigger.setAttribute("aria-labelledby", label.id + " " + id + "-value");
      label.addEventListener("click", (e) => {
        e.preventDefault();
        trigger.focus();
      });
    } else
      trigger.setAttribute(
        "aria-label",
        select.getAttribute("aria-label") || select.name || "Pilih opsi",
      );
    const value = document.createElement("span");
    value.id = id + "-value";
    value.className = "choice-value";
    trigger.append(value);
    popup.className = "choice-popup";
    popup.hidden = true;
    search.type = "search";
    search.placeholder = "Cari pilihan…";
    search.setAttribute("aria-label", "Cari pilihan");
    search.autocomplete = "off";
    list.id = id + "-list";
    list.setAttribute("role", "listbox");
    if (select.multiple) list.setAttribute("aria-multiselectable", "true");
    popup.append(search, list);
    let cursor = 0;
    const visible = () =>
      [...list.querySelectorAll('[role="option"]')].filter(
        (o) => !o.hidden && o.getAttribute("aria-disabled") !== "true",
      );
    function highlight(index) {
      const rows = visible();
      cursor = (index + rows.length) % Math.max(rows.length, 1);
      rows.forEach((o, i) => o.classList.toggle("choice-cursor", i === cursor));
      if (rows[cursor]) {
        trigger.setAttribute("aria-activedescendant", rows[cursor].id);
        rows[cursor].scrollIntoView({ block: "nearest" });
      }
    }
    function close(focus = false) {
      popup.hidden = true;
      wrap.classList.remove("is-open");
      trigger.setAttribute("aria-expanded", "false");
      trigger.removeAttribute("aria-activedescendant");
      if (current?.select === select) current = null;
      if (focus) trigger.focus();
    }
    function render() {
      trigger.disabled = select.disabled;
      value.textContent =
        [...select.selectedOptions]
          .map((o) => (o.value ? o.textContent : "Pilih opsi"))
          .join(", ") || "Pilih opsi";
      trigger.setAttribute("aria-required", String(select.required));
      list.replaceChildren();
      [...select.options].forEach((option, index) => {
        const row = document.createElement("div");
        row.setAttribute("role", "option");
        row.id = id + "-option-" + index;
        row.tabIndex = -1;
        row.dataset.index = index;
        row.textContent = option.value ? option.textContent : "Pilih opsi";
        row.setAttribute("aria-selected", String(option.selected));
        row.setAttribute("aria-disabled", String(option.disabled));
        row.hidden = option.hidden;
        row.addEventListener("click", () => choose(index));
        list.append(row);
      });
      search.hidden = select.options.length < 7;
    }
    function open() {
      if (select.disabled) return;
      current?.close();
      render();
      search.value = "";
      popup.hidden = false;
      wrap.classList.add("is-open");
      trigger.setAttribute("aria-expanded", "true");
      current = { select, close };
      const rows = visible();
      highlight(
        Math.max(
          0,
          rows.findIndex((o) => o.getAttribute("aria-selected") === "true"),
        ),
      );
    }
    function choose(index) {
      const option = select.options[index];
      if (!option || option.disabled) return;
      if (select.multiple) option.selected = !option.selected;
      else select.selectedIndex = index;
      select.dispatchEvent(new Event("input", { bubbles: true }));
      select.dispatchEvent(new Event("change", { bubbles: true }));
      render();
      if (!select.multiple) close(true);
      else {
        trigger.focus();
        highlight(index);
      }
    }
    trigger.addEventListener("click", () => (popup.hidden ? open() : close()));
    trigger.addEventListener("keydown", (event) => {
      if (
        ["ArrowDown", "ArrowUp", "Home", "End", "Enter", " "].includes(
          event.key,
        )
      ) {
        event.preventDefault();
        const wasClosed = popup.hidden;
        if (wasClosed) open();
        else if (event.key === "Enter" || event.key === " ") {
          const row = visible()[cursor];
          if (row) choose(Number(row.dataset.index));
        } else
          highlight(
            event.key === "Home"
              ? 0
              : event.key === "End"
                ? visible().length - 1
                : cursor + (event.key === "ArrowUp" ? -1 : 1),
          );
      } else if (event.key.length === 1 && !event.ctrlKey && !event.metaKey) {
        if (popup.hidden) open();
        const match = visible().findIndex((o) =>
          o.textContent
            .toLocaleLowerCase()
            .startsWith(event.key.toLocaleLowerCase()),
        );
        if (match >= 0) highlight(match);
      }
    });
    search.addEventListener("input", () => {
      const text = search.value.toLocaleLowerCase();
      [...list.children].forEach(
        (row) =>
          (row.hidden = !row.textContent.toLocaleLowerCase().includes(text)),
      );
      highlight(0);
    });
    search.addEventListener("keydown", (event) => {
      if (event.key === "ArrowDown" || event.key === "ArrowUp") {
        event.preventDefault();
        highlight(cursor + (event.key === "ArrowDown" ? 1 : -1));
      }
      if (event.key === "Enter") {
        event.preventDefault();
        const row = visible()[cursor];
        if (row) choose(Number(row.dataset.index));
      }
    });
    wrap.addEventListener("keydown", (event) => {
      if (event.key === "Escape") {
        event.preventDefault();
        close(true);
      }
      if (event.key === "Tab") close();
    });
    select.addEventListener("change", render);
    select.addEventListener("invalid", (event) => {
      event.preventDefault();
      trigger.setAttribute("aria-invalid", "true");
      trigger.focus();
      open();
    });
    select.addEventListener("change", () =>
      trigger.removeAttribute("aria-invalid"),
    );
    select.form?.addEventListener("reset", () => requestAnimationFrame(render));
    new MutationObserver(render).observe(select, {
      childList: true,
      subtree: true,
      attributes: true,
      attributeFilter: ["disabled", "label", "selected"],
    });
    render();
  }
  document.querySelectorAll("select").forEach(enhance);
  document.addEventListener("click", (event) => {
    if (
      current &&
      !event.composedPath().includes(current.select.closest(".choice"))
    )
      current.close();
  });
  // New rows in the cashier form use the same controls.
  new MutationObserver((records) =>
    records.forEach((record) =>
      record.addedNodes.forEach((node) => {
        if (node.nodeType !== 1) return;
        if (node.matches("select")) enhance(node);
        node.querySelectorAll?.("select").forEach(enhance);
      }),
    ),
  ).observe(document.body, { childList: true, subtree: true });
})();
