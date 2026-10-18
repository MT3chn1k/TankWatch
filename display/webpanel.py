"""An LED panel drawn in a web browser: a page that redraws the pixels several times a second.
Used by the display agent (as a virtual Unicorn HAT Mini) and by the virtual Galactic Unicorn sign."""
import http.server, json, threading

PAGE = """<!doctype html><meta charset=utf-8><title>%(title)s</title>
<meta name=viewport content="width=device-width,initial-scale=1">
<style>body{background:#111;margin:0;display:grid;place-items:center;height:100vh;font:14px sans-serif;color:#888}
canvas{width:min(94vw,1200px);image-rendering:pixelated}</style><canvas id=c></canvas><p>%(title)s</p>
<script>const c=document.getElementById('c'),g=c.getContext('2d');
async function tick(){try{const f=await (await fetch('frame.json')).json();const s=24;c.width=f.w*s;c.height=f.h*s;
g.fillStyle='#000';g.fillRect(0,0,c.width,c.height);f.p.forEach((p,i)=>{const x=i%%f.w,y=Math.floor(i/f.w);
g.fillStyle=(p[0]+p[1]+p[2])?`rgb(${p})`:'#1b1b1b';g.beginPath();g.arc(x*s+s/2,y*s+s/2,s*0.38,0,7);g.fill();});}catch(e){}
setTimeout(tick,100)}tick();</script>"""


class WebPanel:
    def __init__(self, width, height, port, title="TankWatch display"):
        self.w, self.h = width, height
        self.fb = [(0, 0, 0)] * (width * height)
        page = (PAGE % {"title": title}).encode()
        panel = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                if self.path.startswith("/frame.json"):
                    body, kind = json.dumps({"w": panel.w, "h": panel.h, "p": panel.fb}).encode(), "application/json"
                else:
                    body, kind = page, "text/html"
                self.send_response(200)
                self.send_header("Content-Type", kind)
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *a):
                pass

        server = http.server.ThreadingHTTPServer(("0.0.0.0", port), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()

    def show(self, fb):
        """fb: a flat list of (r, g, b), row by row."""
        self.fb = list(fb)
