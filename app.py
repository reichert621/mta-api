# coding: utf-8
"""
    mta-api-sanity
    ~~~~~~

    Expose the MTA's real-time subway feed as a json api

    :copyright: (c) 2014 by Jon Thornton.
    :license: BSD, see LICENSE for more details.
"""

from mtapi.mtapi import Mtapi
from flask import Flask, request, jsonify, render_template, abort, redirect
from json import JSONEncoder
from datetime import datetime
from functools import wraps, reduce
import json
import logging
import os

app = Flask(__name__)
app.config.update(MAX_TRAINS=10, MAX_MINUTES=30, CACHE_SECONDS=60, THREADED=True)

_SETTINGS_ENV_VAR = "MTAPI_SETTINGS"
_SETTINGS_DEFAULT_PATH = "./settings.cfg"
if _SETTINGS_ENV_VAR in os.environ:
    app.config.from_envvar(_SETTINGS_ENV_VAR)
elif os.path.isfile(_SETTINGS_DEFAULT_PATH):
    app.config.from_pyfile(_SETTINGS_DEFAULT_PATH)
else:
    raise Exception(
        "No configuration found! Create a settings.cfg file or set MTAPI_SETTINGS env variable."
    )

# set debug logging
if app.debug:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )


class CustomJSONEncoder(JSONEncoder):
    def default(self, obj):
        try:
            if isinstance(obj, datetime):
                return obj.isoformat()
            iterable = iter(obj)
        except TypeError:
            pass
        else:
            return list(iterable)
        return JSONEncoder.default(self, obj)


app.json_encoder = CustomJSONEncoder

mta = Mtapi(
    app.config["MTA_KEY"],
    app.config["STATIONS_FILE"],
    max_trains=app.config["MAX_TRAINS"],
    max_minutes=app.config["MAX_MINUTES"],
    expires_seconds=app.config["CACHE_SECONDS"],
    threaded=app.config["THREADED"],
)


def cross_origin(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        resp = f(*args, **kwargs)

        if app.config["DEBUG"]:
            resp.headers["Access-Control-Allow-Origin"] = "*"
        elif "CROSS_ORIGIN" in app.config:
            resp.headers["Access-Control-Allow-Origin"] = app.config["CROSS_ORIGIN"]

        return resp

    return decorated_function


@app.route("/")
@cross_origin
def index():
    return jsonify(
        {
            "title": "MTAPI",
            "readme": "Visit https://github.com/jonthornton/MTAPI for more info",
        }
    )


@app.route("/api/stations", methods=["GET"])
@cross_origin
def stations_by_filter():
    try:
        query = request.args.get("query")
        latitude = request.args.get("latitude")
        longitude = request.args.get("longitude")
        limit = int(request.args.get("limit", 10))

        if query:
            data = mta.get_stations(query, limit)
        elif latitude and longitude:
            location = (float(latitude), float(longitude))
            data = mta.get_by_point(location, limit)
        else:
            data = mta.get_stations(limit=limit)
            # raise ValueError("Missing query or latitude/longitude parameters")

        return _make_envelope(data)

    except Exception as e:
        print(e)
        response = jsonify({"error": str(e)})
        response.status_code = 400
        return response


@app.route("/api/routes/<route>", methods=["GET"])
@cross_origin
def stations_by_route(route):
    try:
        data = mta.get_by_route(route)
        return _make_envelope(data)
    except KeyError as e:
        abort(404)


@app.route("/api/stations/<station_id>", methods=["GET"])
@cross_origin
def by_index(station_id):
    ids = station_id.split(",")
    try:
        data = mta.get_by_id(ids)
        return _make_envelope(data)
    except KeyError as e:
        abort(404)


@app.route("/api/routes", methods=["GET"])
@cross_origin
def routes():
    return jsonify({"data": sorted(mta.get_routes()), "updated": mta.last_update()})


def _envelope_reduce(a, b):
    if a["last_update"] and b["last_update"]:
        return a if a["last_update"] < b["last_update"] else b
    elif a["last_update"]:
        return a
    else:
        return b


def _make_envelope(data):
    time = None
    if data:
        time = reduce(_envelope_reduce, data)["last_update"]
    dump = json.dumps({"data": data, "updated": time}, cls=CustomJSONEncoder)

    return jsonify(json.loads(dump))


if __name__ == "__main__":
    app.run(use_reloader=False)
