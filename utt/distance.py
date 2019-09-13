import pytz
import json
from collections import defaultdict
from datetime import datetime, timedelta

from flask import request, jsonify, Response, url_for, render_template
from sqlalchemy import func

from .app import app

from utt.gct import as_gct, parse_gct
from utt.model import db, \
                      get_station, \
                      get_station_pair, \
                      System, \
                      Station, \
                      Character, \
                      Token, \
                      StationPair, \
                      StationDistanceReading

@app.route('/v1/distance/add', methods=['POST'])
def add_distance():
    payload = request.get_json(force=True)
    mandatory = set(('token', 'source', 'system', 'schedules'))
    missing_attrs = [a for a in mandatory if not payload.get(a)]
    if missing_attrs:
        message = 'Missing attributes: '  + ', '.join(missing_attrs)
        return jsonify({'recorded': False, 'missing': missing_attrs, message: message})

    token_str = payload['token']
    token = Token.query.filter_by(token=token_str).first()
    if token is None:
        return jsonify({'recorded': False, 'message': 'Invalid token'})

    station = get_station(payload['system'], payload['source'])
    count = 0
    new = 0
    for schedule in payload['schedules']:
        destination = get_station(payload['system'], schedule['destination'])
        pair = get_station_pair(station, destination)
        for (departure, distance) in schedule['distances']:
            if not isinstance(distance, (int, float)):
                continue
            distance = int(distance)
            departure = parse_gct(departure) or departure
            count += 1
            existing = StationDistanceReading.query.filter_by(
                station_pair_id=pair.id,
                distance_km=distance,
                when=departure,
            ).first()
            if not existing:
                new += 1
                sdr = StationDistanceReading(
                    station_pair=pair,
                    distance_km=distance,
                    when=departure,
                    token=token,
                )
                db.session.add(sdr)
    db.session.commit()
    print('Recorded {} distance pairs ({} new) for {} by {}'.format(count, new, payload['source'], token.character.name))
    return jsonify({'recorded': True, 'message': 'Recorded {} distance pairs, of which {} were new. +1 brownie point'.format(count, new)})

@app.route('/distance')
def distance_overview():
    station_pairs = defaultdict(dict)

    for sp in StationPair.query.all():
        station_pairs[sp.system.name][str(sp)] = {
            'id': sp.id,
            'count': len(sp.readings),
            'url': url_for('distance_pair', id=sp.id),
        }
    if request.content_type == 'application/json':
        return jsonify(station_pairs)
    return render_template('distance_overview.html', systems=station_pairs)

@app.route('/distance/pair/<id>')
def distance_pair(id):
    id = int(id)
    readings = []
    pair = StationPair.query.filter_by(id=id).one()
    for r in StationDistanceReading.query.filter_by(station_pair_id=id).order_by(StationDistanceReading.when).all():
        readings.append({'x': r.when.astimezone(pytz.UTC).strftime( "%Y-%m-%dT%H:%M:%SZ"), 'y': r.distance_km})

    result = {
        'station_a_name': pair.station_a.name,
        'station_b_name': pair.station_b.name,
        'system_name': pair.system.name,
        'pair_string': str(pair),
        'readings': readings,
    }
    if request.content_type == 'application/json':
        return jsonify(result)
    result['readings'] = json.dumps(result['readings'])
    return render_template('distance_pair.html', **result)

@app.route('/distance/pair/<id>.csv')
def distance_pair_csv(id):
    id = int(id)
    pair = StationPair.query.filter_by(id=id).one()
    rows = ["Time/UTC,Time/GCT,Distance/km\n"]
    for r in StationDistanceReading.query.filter_by(station_pair_id=id).order_by(StationDistanceReading.when).all():
        when = r.when.astimezone(pytz.UTC)
        rows.append('{},{},{}\n'.format(
            when.strftime( "%Y-%m-%dT%H:%M:%SZ"),
            as_gct(when),
            r.distance_km,
        ))
    response = Response(''.join(rows), mimetype='text/csv')
    response.headers['Content-Disposition'] = 'attachment; filename=pair-{}.csv'.format(id)
    return response
