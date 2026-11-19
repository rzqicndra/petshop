"use strict";
// One accessible drawer state, shared by the app and the public navigation.
let activeMenu = null;
const backdrop = document.querySelector(".nav-backdrop");
function closeMenu(restoreFocus = true) {
  if (!activeMenu) return;
  activeMenu.target.classList.remove("is-open");
  activeMenu.button.setAttribute("aria-expanded", "false");
  activeMenu.button.setAttribute("aria-label", "Buka menu");
  if (backdrop) backdrop.hidden = true;
  document.body.classList.remove("menu-open");
  if (restoreFocus) activeMenu.button.focus();
  activeMenu = null;
}
document.querySelectorAll("[data-menu]").forEach((button) =>
  button.addEventListener("click", () => {
    if (activeMenu?.button === button) {
      closeMenu();
      return;
    }
    closeMenu(false);
    const target = document.getElementById(
      button.getAttribute("aria-controls"),
    );
    if (!target) return;
    activeMenu = { button, target };
    target.classList.add("is-open");
    button.setAttribute("aria-expanded", "true");
    button.setAttribute("aria-label", "Tutup menu");
    if (target.id === "sidebar") {
      if (backdrop) backdrop.hidden = false;
      document.body.classList.add("menu-open");
      target.querySelector("button[data-menu-dismiss]")?.focus();
    }
  }),
);
document
  .querySelectorAll("[data-menu-dismiss]")
  .forEach((el) => el.addEventListener("click", () => closeMenu()));
document.addEventListener("click", (event) => {
  if (
    activeMenu &&
    !activeMenu.target.contains(event.target) &&
    !activeMenu.button.contains(event.target)
  )
    closeMenu(false);
});
document.addEventListener("keydown", (event) => {
  if (!activeMenu) return;
  if (event.key === "Escape") {
    event.preventDefault();
    closeMenu();
  }
  if (event.key === "Tab" && activeMenu?.target.id === "sidebar") {
    const items = [
      ...activeMenu.target.querySelectorAll(
        "a[href],button:not([disabled]),select",
      ),
    ].filter((el) => el.getClientRects().length);
    const first = items[0],
      last = items.at(-1);
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last?.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first?.focus();
    }
  }
});
window.matchMedia("(min-width:1001px)").addEventListener("change", (event) => {
  if (event.matches) closeMenu(false);
});
document
  .querySelectorAll("[data-dismiss-message]")
  .forEach((button) =>
    button.addEventListener("click", () =>
      button.closest(".message")?.remove(),
    ),
  );
document.querySelectorAll("[data-auto-filter]").forEach((select) =>
  select.addEventListener("change", () => {
    const category = select.form?.querySelector('[name="category"]');
    if (select.name === "species" && category) category.value = "";
    select.form?.requestSubmit();
  }),
);
const toast = document.getElementById("cart-toast");
let toastTimer;
document.querySelector("[data-toast-close]")?.addEventListener("click", () => {
  if (toast) toast.hidden = true;
});
document.querySelectorAll("form[data-cart-add]").forEach((form) =>
  form.addEventListener("submit", async (event) => {
    if (!window.fetch) return;
    event.preventDefault();
    if (form.dataset.submitting) return;
    form.dataset.submitting = "true";
    const button = form.querySelector("button[type=submit]");
    button.disabled = true;
    try {
      const response = await fetch(form.action, {
        method: "POST",
        body: new FormData(form),
        headers: { "X-Requested-With": "XMLHttpRequest" },
        credentials: "same-origin",
      });
      if (!response.ok) throw new Error("cart");
      const data = await response.json();
      document
        .querySelectorAll("[data-cart-count]")
        .forEach((el) => (el.textContent = String(data.count)));
      if (toast) {
        clearTimeout(toastTimer);
        toast.hidden = false;
        toastTimer = setTimeout(() => (toast.hidden = true), 6500);
      }
    } catch (_) {
      // A network timeout may have occurred after the write. Do not submit twice.
      window.location.assign("/keranjang/");
    } finally {
      delete form.dataset.submitting;
      button.disabled = false;
    }
  }),
);
// File inputs remain real native controls; filenames/previews add feedback without exposing data remotely.
document.querySelectorAll("input[type=file]").forEach((input) => {
  let zone = input.closest(".upload-zone");
  if (!zone) {
    zone = document.createElement("div");
    zone.className = "upload-zone";
    input.before(zone);
    zone.append(input);
    const title = document.createElement("span");
    title.className = "upload-title";
    title.textContent = "Pilih foto atau dokumen";
    const hint = document.createElement("span");
    hint.className = "upload-hint";
    hint.textContent = "JPG, PNG atau PDF · maksimal 5 MB";
    const name = document.createElement("span");
    name.className = "upload-filename";
    name.dataset.uploadName = "";
    name.textContent = "Belum ada file dipilih";
    zone.append(title, hint, name);
  }
  let previewURL = null;
  input.addEventListener("change", () => {
    if (previewURL) {
      URL.revokeObjectURL(previewURL);
      previewURL = null;
    }
    zone.querySelector(".upload-preview")?.remove();
    const file = input.files?.[0];
    zone.querySelector("[data-upload-name]").textContent = file
      ? `${file.name} · ${(file.size / 1024).toFixed(0)} KB`
      : "Belum ada file dipilih";
    input.setCustomValidity(
      file?.size > 5 * 1024 * 1024 ? "Ukuran file maksimal 5 MB." : "",
    );
    if (
      file &&
      file.size <= 5 * 1024 * 1024 &&
      ["image/jpeg", "image/png", "image/webp"].includes(file.type)
    ) {
      previewURL = URL.createObjectURL(file);
      const img = document.createElement("img");
      img.className = "upload-preview";
      img.alt = "Pratinjau file pilihan";
      img.src = previewURL;
      zone.prepend(img);
    }
  });
});
const checkoutMethod = document.getElementById("checkout-method");
if (checkoutMethod) {
  const addresses = document.getElementById("checkout-addresses");
  const review = document.getElementById("checkout-review");
  const summary = document.querySelector("[data-subtotal]");
  const currency = new Intl.NumberFormat("id-ID");
  function syncCheckout() {
    const method = checkoutMethod.querySelector("[name=fulfillment]:checked")?.value;
    const delivery = method === "DELIVERY";
    addresses.hidden = !delivery;
    addresses.querySelectorAll("input").forEach(input => { input.disabled = !delivery; });
    const address = delivery ? checkoutMethod.querySelector("[name=address]:checked")?.value || "" : "";
    if (review && (method !== review.dataset.method || address !== review.dataset.address)) {
      review.hidden = true;
      review.disabled = true;
      review.querySelectorAll("[name=quote]").forEach(input => { input.checked = false; });
    }
    const quote = review && !review.disabled && review.querySelector("[name=quote]:checked");
    const fee = delivery ? (quote ? Number(quote.dataset.fee) : null) : 0;
    summary.querySelector("[data-shipping-total]").textContent = fee === null ? "Pilih kurir" : "Rp" + currency.format(fee);
    summary.querySelector("[data-order-total]").textContent = fee === null ? "—" : "Rp" + currency.format(Number(summary.dataset.subtotal) + fee);
  }
  checkoutMethod.addEventListener("change", syncCheckout);
  window.addEventListener("pageshow", syncCheckout);
  syncCheckout();
}
const bookingFilters = document.querySelector("[data-booking-filters]");
if (bookingFilters) {
  bookingFilters.addEventListener("change", (event) => {
    if (event.target.name === "pet") bookingFilters.elements.paket.value = "";
    bookingFilters.requestSubmit();
  });
}
// A shared confirmation dialog. Server-side authorization remains authoritative.
const confirmation = document.getElementById("confirmation-dialog");
let pendingConfirmation = null;
function dismissConfirmation() {
  confirmation?.close();
  pendingConfirmation?.submitter?.focus();
  pendingConfirmation = null;
}
document
  .querySelectorAll("[data-confirm-cancel]")
  .forEach((button) => button.addEventListener("click", dismissConfirmation));
confirmation?.addEventListener("cancel", () => {
  pendingConfirmation = null;
});
document.getElementById("confirm-continue")?.addEventListener("click", () => {
  const pending = pendingConfirmation;
  if (!pending) return;
  pendingConfirmation = null;
  confirmation.close();
  pending.form.dataset.confirmed = "true";
  if (pending.submitter) pending.form.requestSubmit(pending.submitter);
  else pending.form.requestSubmit();
});
document.querySelectorAll("form:not([data-cart-add])").forEach((form) =>
  form.addEventListener("submit", (event) => {
    if (form.dataset.confirm && form.dataset.confirmed !== "true") {
      if (confirmation?.showModal) {
        event.preventDefault();
        pendingConfirmation = { form, submitter: event.submitter };
        confirmation.querySelector("[data-confirm-description]").textContent =
          form.dataset.confirm;
        confirmation.showModal();
        confirmation.querySelector("button[data-confirm-cancel]")?.focus();
        return;
      }
      if (!window.confirm(form.dataset.confirm)) {
        event.preventDefault();
        return;
      }
    }
    delete form.dataset.confirmed;
    if (form.dataset.submitting === "true") {
      event.preventDefault();
      return;
    }
    form.dataset.submitting = "true";
    setTimeout(
      () =>
        form.querySelectorAll("button[type=submit]").forEach((button) => {
          button.setAttribute("aria-disabled", "true");
          button.classList.add("is-busy");
        }),
      0,
    );
  }),
);
window.addEventListener("pageshow", () => {
  document
    .querySelectorAll("form")
    .forEach((form) => delete form.dataset.submitting);
  document.querySelectorAll(".is-busy").forEach((button) => {
    button.classList.remove("is-busy");
    button.removeAttribute("aria-disabled");
  });
});
// Subtle entrance animation on editorial pages only. Content remains visible without JS.
if (
  !window.matchMedia("(prefers-reduced-motion: reduce)").matches &&
  "IntersectionObserver" in window
) {
  const observer = new IntersectionObserver(
    (entries) =>
      entries.forEach((entry) => {
        if (entry.isIntersecting) {
          entry.target.classList.add("is-visible");
          observer.unobserve(entry.target);
        }
      }),
    { threshold: 0.08 },
  );
  document
    .querySelectorAll(
      ".public .public-section,.public .hero-copy,.public .hero-photo",
    )
    .forEach((el) => {
      el.classList.add("reveal-enabled");
      observer.observe(el);
    });
}
const addCashierItem = document.getElementById("add-cashier-item");
addCashierItem?.addEventListener("click", () => {
  const total = document.getElementById("id_form-TOTAL_FORMS"),
    template = document.getElementById("cashier-empty-row"),
    target = document.getElementById("cashier-items");
  if (!total || !template || !target || Number(total.value) >= 30) return;
  const fragment = template.content.cloneNode(true);
  fragment.querySelectorAll("[id],[name],label[for]").forEach((el) =>
    ["id", "name", "for"].forEach((attr) => {
      if (el.hasAttribute(attr))
        el.setAttribute(
          attr,
          el.getAttribute(attr).replaceAll("__prefix__", total.value),
        );
    }),
  );
  target.append(fragment);
  total.value = String(Number(total.value) + 1);
});

// Optional visibility control for passwords; values are never read or transmitted here.
document.querySelectorAll("input[type=password]").forEach((input) => {
  const wrap = document.createElement("div");
  wrap.className = "password-wrap";
  input.before(wrap);
  wrap.append(input);
  const button = document.createElement("button");
  button.type = "button";
  button.className = "password-toggle";
  button.textContent = "Lihat";
  button.setAttribute("aria-label", "Tampilkan password");
  button.setAttribute("aria-pressed", "false");
  button.addEventListener("click", () => {
    const show = input.type === "password";
    input.type = show ? "text" : "password";
    button.textContent = show ? "Sembunyikan" : "Lihat";
    button.setAttribute("aria-pressed", String(show));
    button.setAttribute(
      "aria-label",
      show ? "Sembunyikan password" : "Tampilkan password",
    );
  });
  wrap.append(button);
});

// Refresh payment state from our server; browser never decides that an invoice is paid.
const invoicePoll = document.querySelector("[data-invoice-poll]");
if (invoicePoll) {
  const poll = async () => {
    if (!document.hidden) {
      try {
        const response = await fetch(invoicePoll.dataset.invoicePoll, {
          credentials: "same-origin",
          headers: { Accept: "application/json" },
        });
        if (
          !response.ok ||
          !response.headers.get("content-type")?.includes("application/json")
        )
          return;
        const state = await response.json();
        if (state.closed) {
          window.location.assign(state.return_url);
          return;
        }
        if (state.status !== invoicePoll.dataset.invoiceStatus) {
          window.location.reload();
          return;
        }
      } catch (_) {
        /* Network interruptions leave payment state unchanged. */
      }
    }
    setTimeout(poll, 10000);
  };
  setTimeout(poll, 10000);
}

// Keep weekly hours easy to dismiss while preserving the customer's current form.
const shopHours = document.querySelector("[data-store-hours]");
document.addEventListener("click", (event) => {
  if (shopHours?.open && !shopHours.contains(event.target)) shopHours.open = false;
});
shopHours?.addEventListener("keydown", (event) => {
  if (event.key === "Escape") {
    shopHours.open = false;
    shopHours.querySelector("summary").focus();
  }
});
// Reveal manual coordinate fields when native validation needs the user's attention.
document.querySelectorAll(".personal-page form").forEach((form) => {
  form.addEventListener("invalid", (event) => {
    const section = event.target.closest("details");
    if (section) section.open = true;
  }, true);
});
