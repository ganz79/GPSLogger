#!/usr/bin/python

# Script created by Neil Lathwood <neil@lathwood.co.uk>

import gps
import httplib, urllib, socket, os
from urllib2 import Request, urlopen, URLError, HTTPError
import shutil
from config import config
from gisFunctions import haversine

if config['APIversion'] == 1 :
 	print "New API in use"
	from webAPIfunctions  import uploadData, checkAPI, currentSession
else :
	print "Old loaded"
	from gpsFunctions import uploadData, checkAPI, currentSession

import tweepy
import sqlite3
import datetime


################################################
# This script is simply to interface with gpsd #
# retrieve the data and then upload to the api #
################################################

# ok, lets write the pid of this script
pidfile = open('/tmp/gpslogger.pid', "w")
pidfile.write("%s" % os.getpid())
pidfile.close

print datetime.datetime.utcnow()

# Connect to Sqlite3 DB
conn = sqlite3.connect(config['DB_NAME'])
c = conn.cursor()

# Listen on port 2947 (gpsd) of localhost
session = gps.gps("localhost", "2947")
session.stream(gps.WATCH_ENABLE | gps.WATCH_NEWSTYLE)

if config['enabletweet'] >0 :
	auth = tweepy.OAuthHandler(config['consumer_key'], config['consumer_secret'])
	auth.set_access_token(config['access_token'], config['access_token_secret'])
	api = tweepy.API(auth)
	print api.me().name, datetime.datetime.utcnow()


dbsessionID = 0
try:
	cur = conn.cursor()
	cur.execute("SELECT value FROM extra WHERE name='session'")
	data = cur.fetchone()
	dbsessionID = int(data[0])
	dbsessionID += 1 	

except sqlite3.Error, e :
	print "Error %s:" % e.args[0]
	dbsessionID = 0


sessionID = currentSession()

print "sessionID   : " , sessionID
print "dbsessionID : " , dbsessionID
if dbsessionID < sessionID :
	print "using sessionID"
	try:
        	cur = conn.cursor()
        	cur.execute("UPDATE extra SET value= ?  WHERE name='session'", [str(sessionID)]) 
        	conn.commit()

	except sqlite3.Error, e :
        	print "Error %s:" % e.args[0]

else :
	print "using dbsessionID"
	sessionID = dbsessionID


print 'Session',sessionID
now=datetime.datetime.now()
curTime = str(now.hour) + ':' + str(now.minute) + ':' + str(now.second)
print curTime

if config['enabletweet'] > 0 :
	if sessionID > 0 :
		api.update_status("We've started a ride, keep a track online http://%s/rides.php?id=%s %s" % (config['website'],sessionID, curTime))
	else:
		api.update_status('GPS logging started @ %s' % (curTime))

os.system('mpg321 --quiet /home/pi/GPSLogger/MP3/logging_started.mp3 &')
sequence = 0
counter = 0
distance = 0
failCounter = 0
apifailcounter = 0
apiok = True
event = 'POSITION'
gpsData = dict()
lon1 = 0 
lat1 = 0
lon2 = 0
lat2 = 0

while True:
	try:
		report = session.next()
		# Wait for a 'TPV' report and display the current time
		# To see all report data, uncomment the line below
		#print report

		if report['class'] == 'TPV':

			print
			print
			print '----------------------------------------'
			print 'latitude         ' , session.fix.latitude
			print 'longitude        ' , session.fix.longitude
			print 'time utc         ' , session.utc,' + ', session.fix.time
			print 'altitude (m)     ' , session.fix.altitude
			print 'speed (m/s)      ' , session.fix.speed
			print 'climb            ' , session.fix.climb
			print 'eps,epx,epv,ept  ' , session.fix.eps , session.fix.epx , session.fix.epv , session.fix.ept
			print 'track            ' , session.fix.track
			print 'satellites       ' , len(session.satellites) , 'in view'
			print 'mode             ' , session.fix.mode
			print 'min mode to use  ' , config['allowedGPSmodes']

			if session.fix.mode >= int(config['allowedGPSmodes']):
				sequence += 1
				counter += 1
				print 'sequence         ' , sequence

				lon2 = session.fix.longitude
				lat2 = session.fix.latitude

				if lon1 <> 0 and lat1 <> 0 and lon2 <> 0 and lat2 <> 0 :
					distance = haversine(lon1, lat1, lon2, lat2)
					if distance < 3 :
						distance = 0
				else :
					distance = 0

				lon1 = lon2
				lat1 = lat2
				lon2 = 0
				lat2 = 0

				gpsData['posid'] = int(str(sessionID)+str(sequence)) 
				gpsData['event'] = event
				gpsData['sequence'] = sequence
				gpsData['trip'] = sessionID
				gpsData['latitude'] = session.fix.latitude
				gpsData['longitude'] = session.fix.longitude
				gpsData['timeutc'] = session.utc
				gpsData['systimeutc'] = datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S%Z")
				gpsData['altitude'] = session.fix.altitude
				gpsData['eps'] = session.fix.eps
				gpsData['epx'] = session.fix.epx
				gpsData['epv'] = session.fix.epv
				gpsData['ept'] = session.fix.ept
				gpsData['speed'] = session.fix.speed
				gpsData['climb'] = session.fix.climb
				gpsData['track'] = session.fix.track
				gpsData['mode'] = session.fix.mode
				gpsData['satellites'] = len(session.satellites)
				gpsData['distance'] = distance

				if apiok == True :

					try :
						uploadResponse = uploadData(gpsData)
					except Exception, e:
					# except :
						uploadResponse = "ERROR"
						print 'Upload error : ' , e
				else :
					print 'API hold retry in ' , config['api-retry'] - apifailcounter 
					apifailcounter += 1

				if counter >= config['tweetTime'] and config['enabletweet'] > 0:
					os.system('mpg321 --quiet /home/pi/GPSLogger/MP3/logging_data.mp3 &')
					print 'Updating twitter',datetime.datetime.utcnow()
					now=datetime.datetime.now()
					curTime = str(now.hour) + ':' + str(now.minute) + ':' + str(now.second)
					api.update_status("Hey, see where we are riding right now http://%s/rides.php?id=%s @ %s" % (config['website'],sessionID,curTime))
					counter = 0

				if uploadResponse != 'OK':
					# Write data to local sqlitedb
					print uploadResponse,datetime.datetime.utcnow()
					apiok = False
					gpsDataStore = [event, sequence, sessionID, session.fix.latitude, session.fix.longitude, session.utc, datetime.datetime.utcnow() , session.fix.altitude, session.fix.eps, session.fix.epx, session.fix.epv, session.fix.ept, session.fix.speed, session.fix.climb, session.fix.track, session.fix.mode, len(session.satellites), distance]
					try :
						c.execute("INSERT INTO gpslog (event, sequence, trip, latitude, longitude, timeutc, systimeutc, altitude, eps, epx, epv, ept, speed, climb, track, mode, satellites, distance ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?);", gpsDataStore)
						conn.commit()
						print "Data save OK " , datetime.datetime.utcnow()
					except Exception, e:
						print "Data save Error" , datetime.datetime.utcnow()
						print e

					if apifailcounter > config['api-retry'] :
						print "API hold reset"
						apiok = True
						apifailcounter = 0

				else:
					print 'Data uploaded ok', datetime.datetime.utcnow()
			else:
				failCounter += 1
				print 'Poor position information form  gpsd' , datetime.datetime.utcnow()
				if failCounter >= 60:
					print 'Playing gps error file' , datetime.datetime.utcnow()
					os.system('mpg321 --quiet /home/pi/GPSLogger/MP3/gps_error.mp3 &')
					failCounter = 0

	except KeyError:
		pass
	except KeyboardInterrupt:
		os.remove('/tmp/gpslogger.pid')
		quit()
	except StopIteration:
		os.remove('/tmp/gpslogger.pid')
		session = None
		print "GPSD has terminated",datetime.datetime.utcnow()

