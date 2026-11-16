(function () {
  "use strict";

  function setFlipped(card, flipped) {
    card.setAttribute("aria-pressed", flipped ? "true" : "false");
    var openBtn = card.querySelector(".flip-toggle");
    var closeBtn = card.querySelector(".flip-close");
    var front = card.querySelector(".flip-front");
    var back = card.querySelector(".flip-back");
    if (openBtn) openBtn.setAttribute("aria-pressed", flipped ? "true" : "false");
    if (closeBtn) closeBtn.setAttribute("aria-pressed", flipped ? "true" : "false");
    if (front) {
      if (flipped) front.setAttribute("inert", "");
      else front.removeAttribute("inert");
      front.setAttribute("aria-hidden", flipped ? "true" : "false");
    }
    if (back) {
      if (flipped) back.removeAttribute("inert");
      else back.setAttribute("inert", "");
      back.setAttribute("aria-hidden", flipped ? "false" : "true");
    }
  }

  function toggleCard(card) {
    var flipped = card.getAttribute("aria-pressed") !== "true";
    setFlipped(card, flipped);
    var target = card.querySelector(flipped ? ".flip-close" : ".flip-toggle");
    if (target) target.focus();
  }

  function closeCard(card, restoreFocus) {
    if (card.getAttribute("aria-pressed") !== "true") return;
    setFlipped(card, false);
    if (restoreFocus) {
      var openBtn = card.querySelector(".flip-toggle");
      if (openBtn) openBtn.focus();
    }
  }

  function bindToggle(button, card) {
    var fromKey = false;
    button.addEventListener("keydown", function (event) {
      if (event.key !== "Enter" && event.key !== " ") return;
      event.preventDefault();
      if (fromKey) return;
      fromKey = true;
      toggleCard(card);
      setTimeout(function () {
        fromKey = false;
      }, 0);
    });
    button.addEventListener("click", function () {
      if (fromKey) return;
      toggleCard(card);
    });
  }

  document.querySelectorAll("[data-flip-card]").forEach(function (card) {
    var openBtn = card.querySelector(".flip-toggle");
    var closeBtn = card.querySelector(".flip-close");
    if (openBtn) bindToggle(openBtn, card);
    if (closeBtn) bindToggle(closeBtn, card);
  });

  document.addEventListener("keydown", function (event) {
    if (event.key !== "Escape") return;
    document.querySelectorAll('[data-flip-card][aria-pressed="true"]').forEach(function (card) {
      closeCard(card, card.contains(document.activeElement));
    });
  });
})();
