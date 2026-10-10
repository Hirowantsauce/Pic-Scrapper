import json
import os
import queue
import subprocess
import sys
import threading
import time
import uuid
from flask import Flask, Response, jsonify, render_template, request, send_from_directory

import download_images

app = Flask(__name__, static_folder="static", template_folder="templates")

# In-memory storage for jobs
JOBS = {}
JOBS_LOCK = threading.Lock()


class Job:
    def __init__(self, job_id, url, output_dir, options):
        self.id = job_id
        self.url = url
        self.output_dir = output_dir
        self.options = options
        self.status = "queued"  # queued, running, completed, cancelled, error
        self.stage = "init"
        self.percent = 0.0
        self.current_index = 0
        self.total_images = 0
        self.saved_count = 0
        self.skipped_count = 0
        self.failed_count = 0
        self.total_bytes = 0
        self.current_status_text = "Initializing..."
        self.files = []
        self.logs = []
        self.cancel_event = threading.Event()
        self.listeners = []  # list of queue.Queue for SSE
        self.lock = threading.Lock()
        self.start_time = time.time()
        self.end_time = None

    def add_listener(self):
        q = queue.Queue(maxsize=100)
        with self.lock:
            self.listeners.append(q)
            # Push current snapshot
            q.put({
                "type": "snapshot",
                "state": self.to_dict()
            })
        return q

    def remove_listener(self, q):
        with self.lock:
            if q in self.listeners:
                self.listeners.remove(q)

    def broadcast(self, event):
        with self.lock:
            dead = []
            for q in self.listeners:
                try:
                    q.put_nowait(event)
                except queue.Full:
                    dead.append(q)
            for q in dead:
                if q in self.listeners:
                    self.listeners.remove(q)

    def log(self, level, message):
        entry = {
            "timestamp": time.strftime("%H:%M:%S"),
            "level": level,
            "message": message
        }
        self.logs.append(entry)
        if len(self.logs) > 500:
            self.logs.pop(0)
        self.broadcast({"type": "log", "log": entry})

    def to_dict(self):
        return {
            "id": self.id,
            "url": self.url,
            "output_dir": self.output_dir,
            "status": self.status,
            "stage": self.stage,
            "percent": self.percent,
            "current_index": self.current_index,
            "total_images": self.total_images,
            "saved_count": self.saved_count,
            "skipped_count": self.skipped_count,
            "failed_count": self.failed_count,
            "total_bytes": self.total_bytes,
            "current_status_text": self.current_status_text,
            "files": self.files,
            "logs": self.logs[-50:],
            "elapsed_seconds": round((time.time() - self.start_time) if not self.end_time else (self.end_time - self.start_time), 1)
        }


def run_download_job(job: Job):
    job.status = "running"
    job.log("info", f"Started job for URL: {job.url}")

    def progress_callback(ev):
        t = ev.get("type")

        if t == "status":
            job.stage = ev.get("stage", job.stage)
            job.current_status_text = ev.get("message", "")
            job.log("info", ev.get("message", ""))
            job.broadcast({"type": "stage", "stage": job.stage, "message": job.current_status_text})

        elif t == "scraped":
            job.total_images = ev.get("total", 0)
            job.stage = "scraping_done"
            job.current_status_text = f"Found {job.total_images} unique image source(s)"
            job.log("success", f"Discovered {job.total_images} logical images on page.")
            job.broadcast({
                "type": "scraped",
                "total": job.total_images,
                "message": job.current_status_text
            })

        elif t == "progress":
            job.current_index = ev.get("index", job.current_index)
            job.percent = ev.get("percent", job.percent)
            job.current_status_text = ev.get("status", "")
            job.broadcast({
                "type": "progress",
                "index": job.current_index,
                "total": job.total_images,
                "percent": job.percent,
                "status": job.current_status_text
            })

        elif t == "candidates":
            count = ev.get("candidate_count", 0)
            job.log("info", f"Image #{ev.get('index')}: Testing {count} resolution variants...")

        elif t == "log":
            lvl = ev.get("level", "info")
            job.log(lvl, ev.get("message", ""))

        elif t == "image_result":
            status = ev.get("status")
            idx = ev.get("index")
            if status == "saved":
                job.saved_count += 1
                f = ev.get("file")
                job.total_bytes += f.get("size_bytes", 0)
                # Attach relative preview url for the web client
                f["preview_url"] = f"/api/files/{job.id}/{f['filename']}"
                job.files.append(f)
                job.log("success", f"✓ Saved #{idx}: {f['filename']} ({f['dim_str']}, {f['size_kb']} KB)")
                job.broadcast({
                    "type": "image_saved",
                    "file": f,
                    "saved_count": job.saved_count,
                    "total_bytes": job.total_bytes,
                    "index": idx,
                    "total": job.total_images
                })
            elif status == "skipped":
                job.skipped_count += 1
                job.log("warn", f"⚠ Skipped #{idx}: {ev.get('message', '')}")
                job.broadcast({
                    "type": "image_skipped",
                    "skipped_count": job.skipped_count,
                    "index": idx,
                    "total": job.total_images
                })
            elif status == "failed":
                job.failed_count += 1
                job.log("error", f"✕ Failed #{idx}: {ev.get('message', '')}")
                job.broadcast({
                    "type": "image_failed",
                    "failed_count": job.failed_count,
                    "index": idx,
                    "total": job.total_images
                })

        elif t == "cancelled":
            job.status = "cancelled"
            job.stage = "cancelled"
            job.current_status_text = "Download cancelled by user"
            job.log("warn", "Download process was cancelled.")
            job.broadcast({"type": "cancelled"})

        elif t == "done":
            job.status = "completed" if job.status != "cancelled" else "cancelled"
            job.stage = "finished"
            job.percent = 100.0
            job.current_status_text = f"Completed: {job.saved_count} saved of {job.total_images}"
            job.log("success", f"Done! {job.saved_count} images saved to '{job.output_dir}'")
            job.broadcast({
                "type": "done",
                "saved_count": job.saved_count,
                "total": job.total_images,
                "output": job.output_dir
            })

        elif t == "error":
            job.status = "error"
            job.stage = "error"
            msg = ev.get("message", "An unknown error occurred.")
            job.current_status_text = msg
            job.log("error", msg)
            job.broadcast({"type": "error", "message": msg})

    try:
        download_images.download_images(
            url=job.url,
            output=job.output_dir,
            render=job.options.get("render", False),
            deep=job.options.get("deep", False),
            no_upgrade=job.options.get("no_upgrade", False),
            min_dim=job.options.get("min_dim", 0),
            debug=job.options.get("debug", False),
            progress_callback=progress_callback,
            is_cancelled=job.cancel_event.is_set
        )
    except Exception as e:
        job.status = "error"
        job.stage = "error"
        job.current_status_text = str(e)
        job.log("error", f"Fatal error: {e}")
        job.broadcast({"type": "error", "message": str(e)})
    finally:
        job.end_time = time.time()
        if job.status not in ("completed", "cancelled", "error"):
            job.status = "completed"
            job.stage = "finished"
            job.percent = 100.0
            job.broadcast({"type": "done", "saved_count": job.saved_count, "total": job.total_images})


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/system")
def system_info():
    pillow_ok = download_images.Image is not None
    playwright_ok = False
    try:
        import playwright
        playwright_ok = True
    except ImportError:
        pass

    return jsonify({
        "workspace": os.path.abspath("."),
        "default_output": os.path.abspath("downloaded_images"),
        "pillow_available": pillow_ok,
        "playwright_available": playwright_ok,
        "python_version": sys.version.split()[0]
    })


@app.route("/api/jobs/start", methods=["POST"])
def start_job():
    data = request.get_json() or {}
    url = (data.get("url") or "").strip()
    if not url:
        return jsonify({"error": "URL is required"}), 400

    if not (url.startswith("http://") or url.startswith("https://")):
        url = "https://" + url

    output_dir = data.get("output_dir", "").strip() or "downloaded_images"
    # Resolve relative to current working dir
    if not os.path.isabs(output_dir):
        output_dir = os.path.abspath(output_dir)

    options = {
        "render": bool(data.get("render", False)),
        "deep": bool(data.get("deep", False)),
        "no_upgrade": bool(data.get("no_upgrade", False)),
        "min_dim": int(data.get("min_dim", 0) or 0),
        "debug": bool(data.get("debug", False)),
    }

    job_id = str(uuid.uuid4())[:8]
    job = Job(job_id, url, output_dir, options)

    with JOBS_LOCK:
        JOBS[job_id] = job

    t = threading.Thread(target=run_download_job, args=(job,), daemon=True)
    t.start()

    return jsonify({
        "job_id": job_id,
        "status": "queued",
        "url": url,
        "output_dir": output_dir
    })


@app.route("/api/jobs/<job_id>/status")
def get_job_status(job_id):
    with JOBS_LOCK:
        job = JOBS.get(job_id)
    if not job:
        return jsonify({"error": "Job not found"}), 404
    return jsonify(job.to_dict())


@app.route("/api/jobs/<job_id>/cancel", methods=["POST"])
def cancel_job(job_id):
    with JOBS_LOCK:
        job = JOBS.get(job_id)
    if not job:
        return jsonify({"error": "Job not found"}), 404

    job.cancel_event.set()
    job.log("warn", "Cancellation requested...")
    return jsonify({"status": "cancelling", "job_id": job_id})


@app.route("/api/jobs/<job_id>/events")
def job_events(job_id):
    with JOBS_LOCK:
        job = JOBS.get(job_id)
    if not job:
        return jsonify({"error": "Job not found"}), 404

    listener = job.add_listener()

    def stream():
        try:
            while True:
                try:
                    event = listener.get(timeout=25)
                    yield f"data: {json.dumps(event)}\n\n"
                    if event.get("type") in ("done", "cancelled", "error"):
                        # Keep connection alive briefly then stop or let client disconnect
                        pass
                except queue.Empty:
                    # Keep alive ping
                    yield ": ping\n\n"
        except GeneratorExit:
            pass
        finally:
            job.remove_listener(listener)

    return Response(
        stream(),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive"
        }
    )


@app.route("/api/files/<job_id>/<filename>")
def serve_image(job_id, filename):
    with JOBS_LOCK:
        job = JOBS.get(job_id)
    if not job:
        return jsonify({"error": "Job not found"}), 404

    return send_from_directory(job.output_dir, filename)


@app.route("/api/open-folder", methods=["POST"])
def open_folder():
    data = request.get_json() or {}
    folder_path = data.get("path")
    if not folder_path:
        folder_path = os.path.abspath("downloaded_images")

    os.makedirs(folder_path, exist_ok=True)
    abs_path = os.path.abspath(folder_path)

    try:
        if sys.platform == "win32":
            os.startfile(abs_path)
        elif sys.platform == "darwin":
            subprocess.Popen(["open", abs_path])
        else:
            subprocess.Popen(["xdg-open", abs_path])
        return jsonify({"success": True, "path": abs_path})
    except Exception as e:
        return jsonify({"error": str(e), "path": abs_path}), 500


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    print(f"\n==================================================")
    print(f" Wallpics Ultra-HD Web UI running at:")
    print(f" http://127.0.0.1:{port}")
    print(f"==================================================\n")
    app.run(host="127.0.0.1", port=port, debug=False)
