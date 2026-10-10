/**
 * Wallpics PRO MAX - Frontend Application Logic
 */

document.addEventListener("DOMContentLoaded", () => {
    // DOM Elements
    const inputUrl = document.getElementById("inputUrl");
    const btnPasteUrl = document.getElementById("btnPasteUrl");
    const btnClearUrl = document.getElementById("btnClearUrl");
    const optRender = document.getElementById("optRender");
    const optDeep = document.getElementById("optDeep");
    const optUpgrade = document.getElementById("optUpgrade");
    const optMinDim = document.getElementById("optMinDim");
    const minDimLabel = document.getElementById("minDimLabel");
    const inputOutputDir = document.getElementById("inputOutputDir");
    const btnExploreOutput = document.getElementById("btnExploreOutput");
    const btnStartDownload = document.getElementById("btnStartDownload");
    const btnCancelDownload = document.getElementById("btnCancelDownload");
    const btnOpenFolderNav = document.getElementById("btnOpenFolderNav");
    const btnOpenFolderGallery = document.getElementById("btnOpenFolderGallery");

    // Progress Elements
    const progressSection = document.getElementById("progressSection");
    const currentStageBadge = document.getElementById("currentStageBadge");
    const statusHeadline = document.getElementById("statusHeadline");
    const percentNumber = document.getElementById("percentNumber");
    const progressBarFill = document.getElementById("progressBarFill");
    const substatusText = document.getElementById("substatusText");
    const etaText = document.getElementById("etaText");
    const metricTotal = document.getElementById("metricTotal");
    const metricProcessed = document.getElementById("metricProcessed");
    const metricSaved = document.getElementById("metricSaved");
    const metricSkipped = document.getElementById("metricSkipped");
    const metricSize = document.getElementById("metricSize");

    // Gallery Elements
    const gallerySection = document.getElementById("gallerySection");
    const galleryCounterPill = document.getElementById("galleryCounterPill");
    const imagesGrid = document.getElementById("imagesGrid");
    const filterChips = document.querySelectorAll(".filter-chip");

    // Terminal Elements
    const terminalConsole = document.getElementById("terminalConsole");
    const chkAutoScroll = document.getElementById("chkAutoScroll");
    const btnClearLogs = document.getElementById("btnClearLogs");
    const btnCopyLogs = document.getElementById("btnCopyLogs");
    const btnToggleTerminal = document.getElementById("btnToggleTerminal");
    const terminalToggleIcon = document.getElementById("terminalToggleIcon");
    const systemStatusText = document.getElementById("systemStatusText");

    // Lightbox Elements
    const lightboxModal = document.getElementById("lightboxModal");
    const lightboxBackdrop = document.getElementById("lightboxBackdrop");
    const lightboxClose = document.getElementById("lightboxClose");
    const lightboxImage = document.getElementById("lightboxImage");
    const lightboxFilename = document.getElementById("lightboxFilename");
    const lightboxSpecs = document.getElementById("lightboxSpecs");
    const lightboxDownloadBtn = document.getElementById("lightboxDownloadBtn");
    const lightboxSourceBtn = document.getElementById("lightboxSourceBtn");

    // State Variables
    let currentJobId = null;
    let eventSource = null;
    let elapsedTimer = null;
    let startTime = null;
    let totalBytesSaved = 0;
    let allDownloadedFiles = [];
    let activeFilter = "all";

    // Initialize System Status
    fetch("/api/system")
        .then(res => res.json())
        .then(data => {
            let statusParts = ["Engine Ready"];
            if (data.pillow_available) statusParts.push("Pillow Active");
            if (data.playwright_available) statusParts.push("Playwright Ready");
            systemStatusText.textContent = statusParts.join(" • ");
            if (data.default_output && !inputOutputDir.value) {
                inputOutputDir.value = data.default_output;
            }
        })
        .catch(err => {
            console.error("Failed to load system info", err);
        });

    // Preset Pill Click Handlers
    document.querySelectorAll(".preset-pill").forEach(pill => {
        pill.addEventListener("click", () => {
            const url = pill.getAttribute("data-url");
            inputUrl.value = url;
            inputUrl.focus();
            btnClearUrl.style.display = "inline-flex";
            if (url.includes("unsplash") || url.includes("wallpapercave")) {
                optRender.checked = true; // Recommend browser render for dynamic galleries
            }
        });
    });

    // URL input interactions
    inputUrl.addEventListener("input", () => {
        btnClearUrl.style.display = inputUrl.value.trim() ? "inline-flex" : "none";
    });

    btnClearUrl.addEventListener("click", () => {
        inputUrl.value = "";
        btnClearUrl.style.display = "none";
        inputUrl.focus();
    });

    btnPasteUrl.addEventListener("click", async () => {
        try {
            const text = await navigator.clipboard.readText();
            if (text) {
                inputUrl.value = text.trim();
                btnClearUrl.style.display = "inline-flex";
            }
        } catch (err) {
            alert("Clipboard access not permitted. Please paste manually into the field.");
        }
    });

    // Min Dimension filter select label update
    optMinDim.addEventListener("change", () => {
        const val = optMinDim.value;
        if (val === "0") minDimLabel.textContent = "Any Resolution";
        else minDimLabel.textContent = `${val}px+ Minimum`;
    });

    // Open output folder actions
    async function triggerOpenFolder() {
        const folder = inputOutputDir.value.trim() || "downloaded_images";
        try {
            const res = await fetch("/api/open-folder", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ path: folder })
            });
            const data = await res.json();
            if (data.success) {
                appendLog("system", `Opened folder in Windows Explorer: ${data.path}`);
            } else {
                appendLog("error", `Could not open folder: ${data.error || "Unknown error"}`);
            }
        } catch (e) {
            appendLog("error", `Failed to trigger folder opening: ${e.message}`);
        }
    }

    btnExploreOutput.addEventListener("click", triggerOpenFolder);
    btnOpenFolderNav.addEventListener("click", triggerOpenFolder);
    btnOpenFolderGallery.addEventListener("click", triggerOpenFolder);

    // Terminal Controls
    btnClearLogs.addEventListener("click", () => {
        terminalConsole.innerHTML = "";
    });

    btnCopyLogs.addEventListener("click", () => {
        const text = terminalConsole.innerText;
        navigator.clipboard.writeText(text).then(() => {
            const orig = btnCopyLogs.textContent;
            btnCopyLogs.textContent = "Copied!";
            setTimeout(() => btnCopyLogs.textContent = orig, 1500);
        });
    });

    let terminalCollapsed = false;
    btnToggleTerminal.addEventListener("click", () => {
        terminalCollapsed = !terminalCollapsed;
        terminalConsole.style.display = terminalCollapsed ? "none" : "flex";
        terminalToggleIcon.textContent = terminalCollapsed ? "▲" : "▼";
    });

    function appendLog(level, message, timestamp) {
        const time = timestamp || new Date().toLocaleTimeString();
        const line = document.createElement("div");
        line.className = `log-line log-${level}`;
        line.innerHTML = `<span class="log-time">[${time}]</span> ${escapeHtml(message)}`;
        terminalConsole.appendChild(line);

        if (chkAutoScroll.checked) {
            terminalConsole.scrollTop = terminalConsole.scrollHeight;
        }
    }

    function escapeHtml(str) {
        return (str || "").replace(/[&<>"']/g, m => ({
            "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
        }[m]));
    }

    // Number Tween Helper
    function animateNumber(element, start, end, duration = 300) {
        const startTime = performance.now();
        function update(now) {
            const progress = Math.min((now - startTime) / duration, 1);
            const val = Math.floor(start + (end - start) * progress);
            element.textContent = val;
            if (progress < 1) {
                requestAnimationFrame(update);
            }
        }
        requestAnimationFrame(update);
    }

    // Start Download Process
    btnStartDownload.addEventListener("click", async () => {
        const url = inputUrl.value.trim();
        if (!url) {
            alert("Please enter a valid webpage URL to scrape.");
            inputUrl.focus();
            return;
        }

        const payload = {
            url: url,
            output_dir: inputOutputDir.value.trim() || "downloaded_images",
            render: optRender.checked,
            deep: optDeep.checked,
            no_upgrade: !optUpgrade.checked,
            min_dim: parseInt(optMinDim.value, 10) || 0,
            debug: true
        };

        // Reset state
        totalBytesSaved = 0;
        allDownloadedFiles = [];
        imagesGrid.innerHTML = "";
        percentNumber.textContent = "0";
        progressBarFill.style.width = "0%";
        metricTotal.textContent = "0";
        metricProcessed.textContent = "0";
        metricSaved.textContent = "0";
        metricSkipped.textContent = "0";
        metricSize.innerHTML = `0.0 <span class="unit">MB</span>`;
        galleryCounterPill.textContent = "0 Saved";

        // Show sections
        progressSection.style.display = "block";
        gallerySection.style.display = "block";
        currentStageBadge.textContent = "Initiating";
        statusHeadline.textContent = "Dispatching download job...";
        substatusText.textContent = "Connecting to server...";

        // Button state
        btnStartDownload.style.display = "none";
        btnCancelDownload.style.display = "inline-flex";

        startTime = Date.now();
        if (elapsedTimer) clearInterval(elapsedTimer);
        elapsedTimer = setInterval(() => {
            const elapsed = Math.floor((Date.now() - startTime) / 1000);
            etaText.textContent = `Elapsed: ${elapsed}s`;
        }, 1000);

        appendLog("system", `Starting scraper for: ${url}`);

        try {
            const res = await fetch("/api/jobs/start", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(payload)
            });

            if (!res.ok) {
                const err = await res.json();
                throw new Error(err.error || "Failed to start job");
            }

            const data = await res.json();
            currentJobId = data.job_id;
            connectEventSource(currentJobId);

        } catch (err) {
            appendLog("error", `Failed to start download: ${err.message}`);
            finishJobUI("error", `Error: ${err.message}`);
        }
    });

    // Cancel Download
    btnCancelDownload.addEventListener("click", async () => {
        if (!currentJobId) return;
        btnCancelDownload.disabled = true;
        btnCancelDownload.querySelector(".btn-text").textContent = "Cancelling...";

        try {
            await fetch(`/api/jobs/${currentJobId}/cancel`, { method: "POST" });
            appendLog("warn", "Cancellation command sent to server.");
        } catch (err) {
            appendLog("error", `Cancellation request failed: ${err.message}`);
        }
    });

    // Connect to Server-Sent Events (SSE)
    function connectEventSource(jobId) {
        if (eventSource) {
            eventSource.close();
        }

        eventSource = new EventSource(`/api/jobs/${jobId}/events`);

        eventSource.onmessage = (e) => {
            if (!e.data || e.data.startsWith(":")) return;
            try {
                const data = JSON.parse(e.data);
                handleServerEvent(data);
            } catch (err) {
                console.error("Error parsing SSE data", err);
            }
        };

        eventSource.onerror = (err) => {
            console.warn("SSE connection closed or lost", err);
            // Check job status with direct fetch in case of stream drop
            checkStatusFallback(jobId);
        };
    }

    async function checkStatusFallback(jobId) {
        try {
            const res = await fetch(`/api/jobs/${jobId}/status`);
            if (res.ok) {
                const job = await res.json();
                if (job.status === "completed" || job.status === "cancelled" || job.status === "error") {
                    finishJobUI(job.status, job.current_status_text);
                }
            }
        } catch (e) {}
    }

    // Process incoming SSE events
    function handleServerEvent(ev) {
        const type = ev.type;

        if (type === "stage") {
            const stageNames = {
                "connecting": "Connecting",
                "rendering": "Browser Rendering",
                "parsing": "DOM Parsing",
                "scraping_done": "Analysis Done",
                "finished": "Completed",
                "cancelled": "Cancelled",
                "error": "Error"
            };
            currentStageBadge.textContent = stageNames[ev.stage] || ev.stage;
            statusHeadline.textContent = ev.message;
        }

        else if (type === "scraped") {
            metricTotal.textContent = ev.total;
            statusHeadline.textContent = `Discovered ${ev.total} unique image items on page`;
            substatusText.textContent = "Analyzing variant resolutions...";
        }

        else if (type === "progress") {
            const curPercent = parseFloat(percentNumber.textContent) || 0;
            const newPercent = Math.min(Math.max(ev.percent, 0), 100);

            animateNumber(percentNumber, curPercent, Math.round(newPercent));
            progressBarFill.style.width = `${newPercent}%`;

            metricProcessed.textContent = `${ev.index} / ${ev.total}`;
            if (ev.status) {
                statusHeadline.textContent = ev.status;
            }
        }

        else if (type === "image_saved") {
            const f = ev.file;
            allDownloadedFiles.push(f);
            totalBytesSaved += (f.size_bytes || 0);

            metricSaved.textContent = ev.saved_count;
            metricSize.innerHTML = `${(totalBytesSaved / (1024 * 1024)).toFixed(1)} <span class="unit">MB</span>`;
            galleryCounterPill.textContent = `${ev.saved_count} Saved`;

            substatusText.textContent = `Latest: ${f.filename} (${f.dim_str})`;

            // Add card to gallery
            addImageToGallery(f);
        }

        else if (type === "image_skipped") {
            metricSkipped.textContent = ev.skipped_count;
        }

        else if (type === "log") {
            const l = ev.log;
            appendLog(l.level, l.message, l.timestamp);
        }

        else if (type === "done") {
            finishJobUI("completed", `Completed: ${ev.saved_count} images downloaded at maximum resolution.`);
        }

        else if (type === "cancelled") {
            finishJobUI("cancelled", "Download cancelled by user.");
        }

        else if (type === "error") {
            finishJobUI("error", ev.message || "An error occurred.");
        }
    }

    // Render an image card into the gallery
    function addImageToGallery(file) {
        const is4K = file.dimensions && (file.dimensions[0] >= 3840 || file.dimensions[1] >= 2160);
        const isFHD = file.dimensions && (file.dimensions[0] >= 1920 || file.dimensions[1] >= 1080);

        let badgeClass = "badge-standard";
        let badgeText = file.dim_str;
        if (is4K) {
            badgeClass = "badge-4k";
            badgeText = `4K UHD • ${file.dim_str}`;
        } else if (isFHD) {
            badgeClass = "badge-fhd";
            badgeText = `FHD • ${file.dim_str}`;
        }

        const card = document.createElement("div");
        card.className = "image-card";
        card.setAttribute("data-is-4k", is4K);
        card.setAttribute("data-is-fhd", isFHD);

        // Filter check
        if (activeFilter === "uhd" && !is4K) card.style.display = "none";
        if (activeFilter === "fhd" && !isFHD) card.style.display = "none";

        card.innerHTML = `
            <div class="image-thumb-wrap" title="Click for full-screen inspection">
                <img class="image-thumb" src="${file.preview_url}" alt="${escapeHtml(file.filename)}" loading="lazy">
                <div class="image-badge-res ${badgeClass}">${badgeText}</div>
            </div>
            <div class="image-card-meta">
                <div class="image-card-name" title="${escapeHtml(file.filename)}">${escapeHtml(file.filename)}</div>
                <div class="image-card-details">
                    <span>${file.size_kb} KB</span>
                    <span>${(file.content_type || "image").split("/")[1] || "img"}</span>
                </div>
                <div class="image-card-actions">
                    <button type="button" class="image-card-btn btn-inspect">Preview</button>
                    <a href="${file.preview_url}" download="${escapeHtml(file.filename)}" class="image-card-btn">Save</a>
                </div>
            </div>
        `;

        // Card inspect click
        const openLightbox = () => {
            showLightbox(file);
        };
        card.querySelector(".image-thumb-wrap").addEventListener("click", openLightbox);
        card.querySelector(".btn-inspect").addEventListener("click", openLightbox);

        imagesGrid.prepend(card);
    }

    // Filter Chips
    filterChips.forEach(chip => {
        chip.addEventListener("click", () => {
            filterChips.forEach(c => c.classList.remove("active"));
            chip.classList.add("active");
            activeFilter = chip.getAttribute("data-filter");

            const cards = imagesGrid.querySelectorAll(".image-card");
            cards.forEach(card => {
                const is4K = card.getAttribute("data-is-4k") === "true";
                const isFHD = card.getAttribute("data-is-fhd") === "true";

                if (activeFilter === "all") {
                    card.style.display = "block";
                } else if (activeFilter === "uhd") {
                    card.style.display = is4K ? "block" : "none";
                } else if (activeFilter === "fhd") {
                    card.style.display = isFHD ? "block" : "none";
                }
            });
        });
    });

    // Lightbox modal handler
    function showLightbox(file) {
        lightboxImage.src = file.preview_url;
        lightboxFilename.textContent = file.filename;
        lightboxSpecs.textContent = `${file.dim_str} • ${file.size_kb} KB • ${file.content_type || "image"}`;
        lightboxDownloadBtn.href = file.preview_url;
        lightboxDownloadBtn.setAttribute("download", file.filename);
        lightboxSourceBtn.href = file.url;
        lightboxModal.style.display = "flex";
    }

    function closeLightbox() {
        lightboxModal.style.display = "none";
        lightboxImage.src = "";
    }

    lightboxClose.addEventListener("click", closeLightbox);
    lightboxBackdrop.addEventListener("click", closeLightbox);
    window.addEventListener("keydown", (e) => {
        if (e.key === "Escape" && lightboxModal.style.display === "flex") {
            closeLightbox();
        }
    });

    // Finalize UI State
    function finishJobUI(status, message) {
        if (eventSource) {
            eventSource.close();
            eventSource = null;
        }
        if (elapsedTimer) {
            clearInterval(elapsedTimer);
            elapsedTimer = null;
        }

        btnCancelDownload.style.display = "none";
        btnCancelDownload.disabled = false;
        btnCancelDownload.querySelector(".btn-text").textContent = "Cancel Operation";

        btnStartDownload.style.display = "inline-flex";

        if (status === "completed") {
            percentNumber.textContent = "100";
            progressBarFill.style.width = "100%";
            currentStageBadge.textContent = "Completed";
            currentStageBadge.style.color = "var(--accent-emerald)";
            currentStageBadge.style.borderColor = "var(--accent-emerald)";
            statusHeadline.textContent = message;
            substatusText.textContent = "All images retrieved and saved in highest quality.";
        } else if (status === "cancelled") {
            currentStageBadge.textContent = "Cancelled";
            currentStageBadge.style.color = "var(--accent-amber)";
            currentStageBadge.style.borderColor = "var(--accent-amber)";
            statusHeadline.textContent = message;
            substatusText.textContent = "Operation stopped.";
        } else {
            currentStageBadge.textContent = "Error";
            currentStageBadge.style.color = "var(--accent-rose)";
            currentStageBadge.style.borderColor = "var(--accent-rose)";
            statusHeadline.textContent = message;
            substatusText.textContent = "An error occurred during extraction.";
        }
    }
});
