// main.js — students will add JavaScript here as features are built

// ------------------------------------------------------------------ //
// Modal infrastructure + inline AJAX form submission                  //
// ------------------------------------------------------------------ //
// Vanilla-JS modal driven by [data-open-modal] and [data-close-modal].
// Stopping playback on close: the iframe's real URL is held in data-src;
// we only assign it to src on open, and clear src on close so the
// YouTube player is fully torn down.
//
// The Add / Edit / Delete forms inside modals carry [data-ajax-form];
// a delegated submit listener intercepts, posts via fetch with the
// X-Requested-With: XMLHttpRequest header, and updates the profile
// table in place on success (or shows an inline error on failure).

(function () {
    // ---------------------------------------------------------------- //
    // SPA Router                                                         //
    // ---------------------------------------------------------------- //

    function navigateTo(urlOrHtml, isHtml = false, pushState = true) {
        if (!isHtml) {
            fetch(urlOrHtml).then(function (resp) {
                if (!resp.ok) throw new Error("HTTP " + resp.status);
                return resp.text();
            }).then(function (html) {
                navigateTo(html, true, pushState);
            }).catch(function (err) {
                console.error("Navigation failed:", err);
            });
            return;
        }

        var html = urlOrHtml;
        var parser = new DOMParser();
        var doc = parser.parseFromString(html, "text/html");

        // 2. Update main content
        var newContent = doc.querySelector(".main-content");
        var currentContent = document.querySelector(".main-content");
        if (newContent && currentContent) {
            currentContent.innerHTML = newContent.innerHTML;
        }

        // 3. Update page title
        document.title = doc.title;

        // 4. Update head (links and styles)
        var headLinks = doc.querySelectorAll("head link[rel='stylesheet'], head style");
        headLinks.forEach(function (el) {
            var exists = false;
            if (el.tagName === "LINK") {
                var href = el.getAttribute("href");
                if (document.querySelector("link[href='" + href + "']")) exists = true;
            }
            if (!exists) {
                document.head.appendChild(el.cloneNode(true));
            }
        });

        // 5. Update navbar active states
        var activeLink = doc.querySelector(".nav-link--active");
        if (activeLink) {
            var href = activeLink.getAttribute("href");
            document.querySelectorAll(".nav-link").forEach(function (link) {
                link.classList.remove("nav-link--active");
                if (link.getAttribute("href") === href) {
                    link.classList.add("nav-link--active");
                }
            });
        }

        // 6. History and UI
        // pushState is handled by the caller for URL changes
        window.scrollTo(0, 0);
    }

    document.addEventListener("click", function (event) {
        var link = event.target.closest("a");
        if (!link) return;
        var href = link.getAttribute("href");
        if (!href || href.startsWith("http") || href.startsWith("#") || link.getAttribute("target") === "_blank") return;

        // Intercept internal links (starting with /), but NOT logout
        if (href.startsWith("/") && href !== "/logout") {
            event.preventDefault();
            history.pushState({}, "", href);
            navigateTo(href, false, false);
        }
    });

    window.addEventListener("popstate", function () {
        navigateTo(window.location.pathname, false, false);
    });

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

    // ---------------------------------------------------------------- //
    // AJAX form helpers (Add / Edit / Delete modals on /profile)        //
    // ---------------------------------------------------------------- //

    function escapeHtml(s) {
        return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
            return ({"&": "&amp;", "<": "&lt;", ">": "&gt;", "\"": "&quot;", "'": "&#39;"})[c];
        });
    }

    function rowHtml(expense) {
        return (
            '<td>' + escapeHtml(expense.date) + '</td>' +
            '<td>' + escapeHtml(expense.description) + '</td>' +
            '<td><span class="category-badge category-badge--' + escapeHtml(expense.category_class) + '">' + escapeHtml(expense.category) + '</span></td>' +
            '<td class="profile-table-num">' + escapeHtml(expense.amount) + '</td>' +
            '<td class="profile-table-actions">' +
                '<a class="profile-table-edit-link" href="/expenses/' + expense.id + '/edit" data-open-modal="edit-modal-' + expense.id + '" aria-label="Edit transaction from ' + escapeHtml(expense.date) + '">Edit</a>' +
                '<a class="profile-table-delete-link" href="/expenses/' + expense.id + '/delete" data-open-modal="delete-modal-' + expense.id + '" aria-label="Delete transaction from ' + escapeHtml(expense.date) + '">Delete</a>' +
            '</td>'
        );
    }

    function renderExpenseRow(expense) {
        var tr = document.createElement("tr");
        tr.setAttribute("data-expense-id", String(expense.id));
        tr.innerHTML = rowHtml(expense);
        return tr;
    }

    function updateExpenseRow(tr, expense) {
        tr.innerHTML = rowHtml(expense);
    }

    function showModalError(modal, message) {
        var box = modal.querySelector(".modal-form-error");
        if (!box) return;
        box.textContent = message;
        box.hidden = false;
    }

    function clearModalError(modal) {
        var box = modal.querySelector(".modal-form-error");
        if (!box) return;
        box.textContent = "";
        box.hidden = true;
    }

    function setCount(delta) {
        // Backwards-compat shim — left in place so any stale callers
        // don't crash. New code uses `renderStats` instead, which
        // overwrites both stat tiles from the server envelope (the
        // single source of truth for grand total + count).
        var el = document.getElementById("profile-txn-count");
        if (!el) return;
        var n = parseInt(el.textContent || "0", 10);
        if (isNaN(n)) n = 0;
        el.textContent = String(Math.max(0, n + delta));
    }

    function renderStats(data) {
        // Overwrite the page-level stat tiles from the AJAX envelope.
        // The server is the source of truth — we don't parse or
        // reformat the rupee string here. Tiles are looked up by id;
        // when called from a page that doesn't have them (e.g. the
        // landing page), the function is a no-op.
        var totalEl = document.getElementById("profile-grand-total");
        var countEl = document.getElementById("profile-txn-count");
        if (totalEl && typeof data.total === "string") {
            totalEl.textContent = data.total;
        }
        if (countEl && typeof data.count === "number") {
            countEl.textContent = String(data.count);
        }
    }

    function resetForm(form) {
        // Add modal: clear every field after a successful add.
        // Edit modal: leave values as-is (the form will close).
        if (form.id === "add-expense-form" || form.action.indexOf("/expenses/add") !== -1) {
            form.reset();
        }
    }

    document.addEventListener("submit", function (event) {
        var form = event.target;
        if (!(form instanceof HTMLFormElement)) return;

        var action = form.action;
        if (!action || action.startsWith("http") || !action.includes(window.location.origin)) return;

        if (form.hasAttribute("data-ajax-form")) {
            var modal = form.closest(".modal");
            // Only intercept inside an open modal — stray submits elsewhere
            // should fall through to native behaviour.
            if (!modal || modal.hidden) return;

            event.preventDefault();
            clearModalError(modal);

            var submitBtn = form.querySelector("[type=submit]");
            if (submitBtn) submitBtn.disabled = true;

            var fd = new FormData(form);
            fetch(action, {
                method: form.method || "POST",
                body: fd,
                headers: { "X-Requested-With": "XMLHttpRequest" }
            }).then(function (resp) {
                if (!resp.ok) {
                    throw new Error("HTTP " + resp.status);
                }
                return resp.json();
            }).then(function (data) {
                if (!data || !data.ok) {
                    showModalError(modal, (data && data.error) || "Please correct the error and try again.");
                    // Echo typed values back into the form so the user
                    // doesn't lose their typing on validation failure.
                    if (data && data.values) {
                        Object.keys(data.values).forEach(function (k) {
                            var el = form.elements[k];
                            if (el) el.value = data.values[k];
                        });
                    }
                    return;
                }

                // Refresh the page-level stat tiles from the envelope (the
                // server is the single source of truth — we don't compute
                // deltas client-side). Runs for Add / Edit / Delete.
                renderStats(data);

                var tbody = document.querySelector(".profile-table tbody");

                if (form.action.indexOf("/delete") !== -1) {
                    // Delete: remove the row + its now-orphaned modals.
                    var row = document.querySelector('tr[data-expense-id="' + data.id + '"]');
                    if (row) row.remove();
                    var dm = document.getElementById("delete-modal-" + data.id);
                    if (dm) dm.remove();
                    var em = document.getElementById("edit-modal-" + data.id);
                    if (em) em.remove();
                } else if (form.action.indexOf("/edit") !== -1) {
                    // Edit: update the existing row's cells in place.
                    var row = document.querySelector('tr[data-expense-id="' + data.expense.id + '"]');
                    if (row) updateExpenseRow(row, data.expense);
                } else if (form.action.indexOf("/add") !== -1) {
                    // Add: prepend a new row + reset the form for the next entry.
                    if (tbody && data.expense) {
                        tbody.insertBefore(renderExpenseRow(data.expense), tbody.firstChild);
                    }
                    resetForm(form);
                }

                closeModal(modal);
            }).catch(function () {
                showModalError(modal, "Could not save — please try again.");
            }).then(function () {
                if (submitBtn) submitBtn.disabled = false;
            });
        } else {
            // SPA-style standard form submission
            event.preventDefault();
            var fd = new FormData(form);
            fetch(action, {
                method: form.method || "POST",
                body: fd
            }).then(function (resp) {
                // Handle redirect by updating URL
                var finalUrl = resp.url;
                if (finalUrl !== window.location.href) {
                    history.pushState({}, "", finalUrl);
                }
                return resp.text();
            }).then(function (html) {
                navigateTo(html, true, false);
            }).catch(function (err) {
                console.error("Form submission failed:", err);
            });
        }
    });
})();