"""The status sign in a web browser: runs the sign's real main.py, unchanged, on emulated Pico hardware, and
draws every frame it would send to the LEDs on a web page.

Environment:
  TANKWATCH_JOIN   the hub's DISPLAY join code (read-only): fills in the hub address and token
  SIGN_CONFIG      the sign's config.json (collectors, labels, locations); hub_url in it is replaced by the join code
  WEB_PORT         default 8091
"""
import json, os, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [HERE, os.path.join(HERE, "..", "..", "display"), os.path.join(HERE, "..", "..", "node")]
import discovery                      # noqa: E402
import emulator                       # noqa: E402
from sim_gfx import W, H              # noqa: E402
from webpanel import WebPanel         # noqa: E402

join = discovery.decode_join(os.environ["TANKWATCH_JOIN"])
if join["role"] != "display":
    raise SystemExit("the virtual sign needs the DISPLAY join code (read-only)")
with open(os.environ.get("SIGN_CONFIG", os.path.join(HERE, "..", "config.example.json")), encoding="utf-8") as fh:
    cfg = json.load(fh)
cfg.update({"hub_url": join["url"], "org": join["org"], "bucket": join["bucket"]})

work = tempfile.mkdtemp(prefix="sign-")            # main.py keeps log.txt and style.txt in its working directory
os.chdir(work)
with open("config.json", "w", encoding="utf-8") as fh:
    json.dump(cfg, fh)

panel = WebPanel(W, H, int(os.environ.get("WEB_PORT", "8091")), "TankWatch status sign (virtual Galactic Unicorn)")
emulator.install(join["token"], on_update=panel.show)
print("virtual sign: hub %s, web page on port %s" % (join["url"], os.environ.get("WEB_PORT", "8091")), flush=True)
emulator.load_main(os.path.join(work, "config.json"), run=True)
