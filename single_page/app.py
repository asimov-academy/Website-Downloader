from functools import wraps
from hmac import compare_digest
import os
import queue
import shutil
import threading
import time
import uuid
from pathlib import Path

from flask import (
    Flask,
    Response,
    jsonify,
    redirect,
    render_template,
    request,
    send_file,
    session,
    url_for,
)

from core import (
    APP_DEBUG,
    APP_HOST,
    APP_PORT,
    APP_SECRET_KEY,
    APP_THREADED,
    DOWNLOAD_FOLDER,
    LOGIN_PASSWORD,
    LOGIN_USERNAME,
    SESSION_CLEANUP_INTERVAL_S,
    SESSION_MAX_AGE_S,
    SSE_HEARTBEAT_INTERVAL_S,
    SSE_MESSAGE_TIMEOUT_S,
    STARTUP_CLEAN_DOWNLOADS,
)
from downloader import WebsiteDownloader, get_site_name, zip_directory


_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_DOWNLOAD_ROOT = Path(DOWNLOAD_FOLDER)
if not _DOWNLOAD_ROOT.is_absolute():
    _DOWNLOAD_ROOT = _PROJECT_ROOT / _DOWNLOAD_ROOT
_DOWNLOAD_ROOT = _DOWNLOAD_ROOT.resolve()

app = Flask(
    __name__,
    template_folder=str(Path(__file__).resolve().parent / 'templates'),
    static_folder=str(Path(__file__).resolve().parent / 'static'),
)
app.config.update(
    SECRET_KEY=APP_SECRET_KEY,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE='Lax',
)

os.makedirs(_DOWNLOAD_ROOT, exist_ok=True)


def _safe_redirect_target(target):
    if not target or not target.startswith('/'):
        return None
    if target.startswith('//'):
        return None
    return target


def _unauthorized_response():
    if request.path == '/start-download':
        return jsonify({'error': 'Sessão expirada. Faça login novamente.'}), 401
    if request.path.startswith('/stream/') or request.path.startswith('/download-file/'):
        return Response('Unauthorized', status=401)

    next_url = request.full_path.rstrip('?') if request.query_string else request.path
    return redirect(url_for('login', next=next_url))


def login_required(view):
    @wraps(view)
    def wrapped_view(*args, **kwargs):
        if not session.get('authenticated'):
            return _unauthorized_response()
        return view(*args, **kwargs)

    return wrapped_view


def cleanup_downloads_folder():
    """Remove all files and folders from downloads directory."""
    try:
        for item in os.listdir(DOWNLOAD_FOLDER):
            item_path = _DOWNLOAD_ROOT / item
            if os.path.isfile(item_path):
                os.remove(item_path)
            elif os.path.isdir(item_path):
                shutil.rmtree(item_path)
        print("Pasta downloads limpa com sucesso")
    except Exception as exc:
        print(f"Erro ao limpar pasta downloads: {exc}")


if STARTUP_CLEAN_DOWNLOADS:
    cleanup_downloads_folder()

message_queues = {}
download_results = {}


def cleanup_abandoned_sessions():
    """Clean up sessions that were never downloaded after the max age."""
    while True:
        time.sleep(SESSION_CLEANUP_INTERVAL_S)
        current_time = time.time()

        sessions_to_remove = []
        for session_id, result in list(download_results.items()):
            if result.get('status') == 'complete' and result.get('created_at'):
                age = current_time - result['created_at']
                if age > SESSION_MAX_AGE_S:
                    zip_path = result.get('zip_path')
                    if zip_path and os.path.exists(zip_path):
                        try:
                            os.remove(zip_path)
                            print(f"Removido arquivo abandonado: {os.path.basename(zip_path)}")
                        except Exception:
                            pass
                    sessions_to_remove.append(session_id)

        for session_id in sessions_to_remove:
            if session_id in message_queues:
                del message_queues[session_id]
            if session_id in download_results:
                del download_results[session_id]


cleanup_thread = threading.Thread(target=cleanup_abandoned_sessions, daemon=True)
cleanup_thread.start()


@app.route('/')
@login_required
def index():
    return render_template('index.html')


@app.route('/login', methods=['GET', 'POST'])
def login():
    if session.get('authenticated'):
        return redirect(url_for('index'))

    error = None
    if request.method == 'POST':
        username = (request.form.get('username') or '').strip()
        password = request.form.get('password') or ''

        if compare_digest(username, LOGIN_USERNAME) and compare_digest(password, LOGIN_PASSWORD):
            session.clear()
            session['authenticated'] = True
            session['username'] = username
            next_url = _safe_redirect_target(request.form.get('next') or request.args.get('next'))
            return redirect(next_url or url_for('index'))

        error = 'Login ou senha incorretos.'

    return render_template('login.html', error=error)


@app.route('/logout', methods=['POST'])
def logout():
    session.clear()
    return redirect(url_for('login'))


@app.route('/start-download', methods=['POST'])
@login_required
def start_download():
    """Start download process and return session ID for SSE."""
    data = request.get_json()
    url = data.get('url')

    if not url:
        return jsonify({'error': 'URL is required'}), 400

    session_id = str(uuid.uuid4())
    message_queues[session_id] = queue.Queue()
    download_results[session_id] = {'status': 'processing', 'zip_path': None, 'filename': None}

    thread = threading.Thread(target=process_download, args=(session_id, url))
    thread.daemon = True
    thread.start()

    return jsonify({'session_id': session_id})


def process_download(session_id, url):
    """Background download process."""
    q = message_queues[session_id]
    request_id = session_id
    download_dir = str(_DOWNLOAD_ROOT / request_id)
    zip_path = str(_DOWNLOAD_ROOT / f"{request_id}.zip")

    def log_callback(message):
        q.put(message)

    try:
        downloader = WebsiteDownloader(url, download_dir, log_callback=log_callback)
        success = downloader.process()

        if not success:
            q.put("Falha no download")
            download_results[session_id] = {'status': 'error', 'error': 'Failed to download site'}
            return

        site_name = get_site_name(url)
        zip_filename = f"{site_name}.zip"

        q.put("Criando arquivo ZIP...")
        zip_directory(download_dir, zip_path)
        shutil.rmtree(download_dir)

        q.put("Download pronto!")
        download_results[session_id] = {
            'status': 'complete',
            'zip_path': zip_path,
            'filename': zip_filename,
            'created_at': time.time(),
        }

    except Exception as exc:
        q.put(f"Erro: {str(exc)}")
        download_results[session_id] = {'status': 'error', 'error': str(exc)}
        try:
            if os.path.exists(download_dir):
                shutil.rmtree(download_dir)
            if os.path.exists(zip_path):
                os.remove(zip_path)
        except Exception:
            pass


@app.route('/stream/<session_id>')
@login_required
def stream(session_id):
    """SSE endpoint for log streaming."""

    def generate():
        if session_id not in message_queues:
            yield "data: Sessão não encontrada\n\n"
            return

        q = message_queues[session_id]
        heartbeat_interval = max(1, min(SSE_HEARTBEAT_INTERVAL_S, SSE_MESSAGE_TIMEOUT_S))

        while True:
            try:
                message = q.get(timeout=heartbeat_interval)
                # Sanitize: SSE fields must not contain bare newlines
                safe = str(message).replace('\r\n', ' ').replace('\n', ' ').replace('\r', ' ')
                yield f"data: {safe}\n\n"
            except queue.Empty:
                yield ": keepalive\n\n"

            result = download_results.get(session_id, {})
            if result.get('status') in ['complete', 'error']:
                yield f"event: done\ndata: {result['status']}\n\n"
                break


    return Response(
        generate(),
        mimetype='text/event-stream',
        headers={
            'Cache-Control': 'no-cache',
            'X-Accel-Buffering': 'no',  # disables Railway/nginx proxy buffering
            'Connection': 'keep-alive',
        },
    )


@app.route('/status/<session_id>')
@login_required
def status(session_id):
    """Return current download status for resilient SSE reconnect handling."""
    result = download_results.get(session_id)
    if not result:
        return jsonify({'status': 'not_found'}), 404

    return jsonify({
        'status': result.get('status', 'processing'),
        'filename': result.get('filename'),
    })


@app.route('/download-file/<session_id>')
@login_required
def download_file(session_id):
    result = download_results.get(session_id)
    if not result or result.get('status') != 'complete':
        return "Arquivo não encontrado ou ainda não está pronto", 404

    return send_file(
        result['zip_path'],
        as_attachment=True,
        download_name=result['filename'],
        mimetype='application/zip',
    )


def main():
    app.run(host=APP_HOST, port=APP_PORT, debug=APP_DEBUG, threaded=APP_THREADED)


if __name__ == '__main__':
    main()
