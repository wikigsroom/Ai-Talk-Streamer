"""Publish only the five completed, validated live scenario recordings."""
import json
from aiohttp import web


def configure_scenario_gallery(app, root):
    folder = root / 'outputs/vertical/scenarios'

    def manifest():
        path = folder / 'manifest.json'
        return json.loads(path.read_text(encoding='utf-8')) if path.is_file() else {'ok': False, 'items': []}

    async def catalog(request):
        return web.json_response(manifest(), dumps=lambda value: json.dumps(value, ensure_ascii=False))

    async def media(request):
        name = request.match_info['name']
        allowed = {item['id'] + suffix for item in manifest()['items'] for suffix in ('.mp4', '.png')}
        if name not in allowed:
            raise web.HTTPNotFound()
        path = folder / name
        if not path.is_file():
            raise web.HTTPNotFound()
        headers = {'Content-Disposition': 'attachment; filename="' + name + '"'} if request.query.get('download') == '1' else {}
        return web.FileResponse(path, headers=headers)

    async def download(request):
        path = folder / 'portrait-scenario-tests.zip'
        if not manifest().get('ok') or not path.is_file():
            raise web.HTTPNotFound()
        return web.FileResponse(path, headers={'Content-Disposition': 'attachment; filename="portrait-scenario-tests.zip"'})

    async def page(request):
        return web.FileResponse(root / 'web/tests.html')

    app.router.add_get('/tests', page)
    app.router.add_get('/api/studio/tests', catalog)
    app.router.add_get('/tests/media/{name}', media)
    app.router.add_get('/tests/download', download)
