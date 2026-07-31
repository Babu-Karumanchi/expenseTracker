// main.js — students will add JavaScript here as features are built

// ------------------------------------------------------------------ //
// Modal demo                                                          //
// ------------------------------------------------------------------ //
// Vanilla-JS modal driven by [data-open-modal] and [data-close-modal].
// Stopping playback on close: the iframe's real URL is held in data-src;
// we only assign it to src on open, and clear src on close so the
// YouTube player is fully torn down.

(function () {
    function openModal(modal) {
        var iframe = modal.querySelector("iframe[data-src]");
        if (iframe && !iframe.src) {
            iframe.src = iframe.getAttribute("data-src");
        }
        modal.hidden = false;
        modal.setAttribute("aria-hidden", "false");
        document.body.style.overflow = "hidden";
    }

    function closeModal(modal) {
        var iframe = modal.querySelector("iframe[data-src]");
        if (iframe) {
            iframe.src = "";   // unload the iframe -> playback stops
        }
        modal.hidden = true;
        modal.setAttribute("aria-hidden", "true");
        document.body.style.overflow = "";
    }

    document.addEventListener("click", function (event) {
        var opener = event.target.closest("[data-open-modal]");
        if (opener) {
            event.preventDefault();
            var modal = document.getElementById(opener.getAttribute("data-open-modal"));
            if (modal) openModal(modal);
            return;
        }

        var closer = event.target.closest("[data-close-modal]");
        if (closer) {
            event.preventDefault();
            var modal = closer.closest(".modal");
            if (modal) closeModal(modal);
        }
    });

    document.addEventListener("keydown", function (event) {
        if (event.key !== "Escape") return;
        var open = document.querySelector(".modal:not([hidden])");
        if (open) closeModal(open);
    });
})();
