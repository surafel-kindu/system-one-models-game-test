import hmac
import os
from pathlib import Path
import secrets
from urllib.parse import urlencode, urlsplit

from flask import Flask, abort, jsonify, make_response, redirect, render_template, request, session, url_for
from markupsafe import Markup
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.utils import secure_filename

from benchmarks import BenchmarkIndex, filtered_runs, summary
from catalog import GAMES, MODELS, NAMES, lettering
from submissions import SubmissionStore, ValidationError, valid_url, validate
from presentation import page_metadata

BASE = Path(__file__).resolve().parent


def create_app(config=None):
    app = Flask(__name__)
    app.config.update(
        DATA_DIR=os.environ.get('DATA_DIR',str(BASE/'data')),
        BENCHMARK_DIR=os.environ.get('BENCHMARK_DIR',str(BASE/'benchmark-data')),
        REPOSITORY_URL=os.environ.get('REPOSITORY_URL','https://github.com/surafel-kindu/system-one-models-game-test').rstrip('/'),
        PUBLIC_URL=os.environ.get('PUBLIC_URL','').rstrip('/'),
        SUBMISSIONS_PER_HOUR=max(1,int(os.environ.get('SUBMISSIONS_PER_HOUR','5'))),
        MAX_CONTENT_LENGTH=24*1024,
        SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE='Lax',
        SESSION_COOKIE_SECURE=os.environ.get('PUBLIC_URL','').startswith('https://'),
        TRUST_PROXY=os.environ.get('TRUST_PROXY','0')=='1',
    )
    if config:
        app.config.update(config)
    if not valid_url(app.config['REPOSITORY_URL']):
        raise ValueError('REPOSITORY_URL must be an http(s) repository URL')
    if app.config['TRUST_PROXY']:
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1)
    store = SubmissionStore(app.config['DATA_DIR'])
    app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY') or store.secret
    index = BenchmarkIndex(app.config['BENCHMARK_DIR'])
    app.extensions.update(benchmark_index=index, submission_store=store)

    @app.context_processor
    def shared():
        seo = page_metadata(request.endpoint, request.values.get('kind', 'model'))
        origin = (app.config['PUBLIC_URL'] or request.url_root).rstrip('/')
        seo.update(canonical=origin + seo['path'],
                   image=origin + url_for('static', filename=f"social/{seo['key']}-v2.jpg"),
                   image_alt=f"Model Arcade Lab — {seo['title']}. {seo['caption']}",
                   indexable=seo['public'] and request.method == 'GET' and request.endpoint != 'missing')
        return dict(repo=app.config['REPOSITORY_URL'], games=GAMES, models=MODELS, names=NAMES, seo=seo,
                    lettering=lambda word:Markup(lettering(word)))

    @app.after_request
    def headers(response):
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
        response.headers['Content-Security-Policy'] = "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; font-src 'self'; object-src 'none'; base-uri 'self'; form-action 'self'; frame-ancestors 'none'"
        response.headers['Permissions-Policy'] = 'camera=(), microphone=(), geolocation=()'
        if request.path.startswith('/api/') or request.path == '/submit':
            response.headers['Cache-Control'] = 'no-store'
        return response

    @app.get('/healthz')
    def health():
        with store.connect() as db:
            db.execute('SELECT 1')
        return {'status':'ok'}

    @app.get('/')
    def home():
        dataset = index.load()
        return render_template('home.html', page='home', title='Small models. Real decisions.', run_count=len(dataset['runs']))

    @app.get('/benchmarks')
    def benchmarks_page():
        return render_template('benchmarks.html', page='benchmarks', title='Benchmark archive')

    @app.get('/project')
    def project():
        return render_template('project.html',page='project',title='About the experiment')

    @app.get('/contribute')
    def contribute():
        return render_template('contribute.html',page='contribute',title='Build the next experiment')

    @app.get('/api/runs')
    def runs():
        data = index.load()
        selected = filtered_runs(data['runs'],request.args)
        return jsonify(runs=[summary(r) for r in selected],total=len(data['runs']),files=data['files'],warnings=data['warnings'])

    def find_run(run_id):
        return next((r for r in index.load()['runs'] if r['run_id']==run_id),None)

    @app.get('/api/runs/<run_id>')
    def run_detail(run_id):
        run = find_run(run_id)
        if not run:
            abort(404)
        return jsonify(run)

    @app.get('/api/runs/<run_id>/download')
    def run_download(run_id):
        run = find_run(run_id)
        if not run:
            abort(404)
        response = jsonify(run)
        response.headers['Content-Disposition'] = f'attachment; filename="{secure_filename(run_id) or "benchmark"}.json"'
        return response

    @app.route('/submit', methods=['GET','POST'])
    def submit():
        if request.method == 'GET':
            session.setdefault('csrf',secrets.token_urlsafe(32))
            kind = 'game' if request.args.get('kind')=='game' else 'model'
            return render_template('submit.html',page='submit',title='Bring something new',csrf=session['csrf'],kind=kind,values={},errors={})
        payload = request.get_json(silent=True) if request.is_json else request.form.to_dict()
        payload = payload if isinstance(payload,dict) else {}
        token = request.headers.get('X-CSRF-Token') or payload.get('csrf','')
        expected = session.get('csrf','')
        origin = request.headers.get('Origin')
        allowed = urlsplit(app.config['PUBLIC_URL'] or request.host_url)
        try:
            foreign = bool(origin and (urlsplit(origin).scheme,urlsplit(origin).netloc)!=(allowed.scheme,allowed.netloc))
        except ValueError:
            foreign = True
        if not expected or not isinstance(token,str) or not hmac.compare_digest(expected.encode(),token.encode()) or foreign:
            return jsonify(error='Refresh the form and try again.',errors={'form':'The form expired or came from another site.'}),403
        wants_json = request.is_json or request.accept_mimetypes.best == 'application/json'
        try:
            data = validate(payload)
        except ValidationError as error:
            if wants_json:
                return jsonify(error='Check the highlighted fields.',errors=error.errors),400
            return render_template('submit.html',page='submit',title='Bring something new',csrf=expected,
                                   kind='game' if payload.get('kind')=='game' else 'model',values=payload,errors=error.errors),400
        reference,created = store.save(data,request.remote_addr,app.config['SUBMISSIONS_PER_HOUR'])
        if not reference:
            response = jsonify(error='You have reached the hourly submission limit. Please try again later.')
            response.status_code = 429; response.headers['Retry-After'] = '3600'
            return response
        body = '\n\n'.join([f"## {data['kind'].title()} suggestion: {data['name']}",f"Creator: {data['author']}\n{data['author_url']}",
                            f"Source: {data['source_url']}",f"## Description\n{data['description']}",f"## Integration / rules\n{data['instructions']}",
                            f"Delivery: {data['delivery_mode'] or 'model adapter'}\nLicense: {data['license'] or 'Not specified'}",f"Site reference: {reference}"])
        issue_url = app.config['REPOSITORY_URL']+'/issues/new?'+urlencode({'title':f"[{data['kind']}] {data['name']}",'body':body})
        if len(issue_url)>7500:
            body = (f"Website suggestion: {reference}\n\nCreator: {data['author']}\nSource: {data['source_url']}\n\n"
                    f"{data['description'][:400]}\n\n{data['instructions'][:400]}\n\n"
                    "Long instructions were shortened for this prepared issue. The full suggestion is saved in the maintainer's private review queue.")
            issue_url = app.config['REPOSITORY_URL']+'/issues/new?'+urlencode({'title':f"[{data['kind']}] {data['name']}",'body':body})
            if len(issue_url)>7500:
                issue_url = app.config['REPOSITORY_URL']+'/issues/new?'+urlencode({'title':f"[{data['kind']}] suggestion {reference}",
                    'body':f"Website suggestion: {reference}\n\nFull source, creator information, description, and instructions are saved in the maintainer's private review queue. Please add a public summary before publishing this issue."})
        if wants_json:
            return jsonify(reference=reference,status='pending',created=created,issue_url=issue_url),201 if created else 200
        return render_template('thanks.html',page='submit',title='Suggestion received',reference=reference,issue_url=issue_url),201 if created else 200

    @app.errorhandler(404)
    def missing(error):
        if request.path.startswith('/api/'):
            return jsonify(error='Run not found.'),404
        return render_template('error.html',page='',title='Page not found',message='This page has moved or does not exist.',code=404),404

    @app.errorhandler(413)
    def too_large(error):
        return jsonify(error='This submission is too large. Keep the full request under 24 KiB.'),413

    return app
