#       pybit-web
#       Copyright 2012:
#
#		Nick Davidson <nickd@toby-churchill.com>,
#		Simon Haswell <simonh@toby-churchill.com>,
#		Neil Williams <neilw@toby-churchill.com>,
#		James Bennet <github@james-bennet.com / James.Bennet@toby-churchill.com>
#
#       This program is free software; you can redistribute it and/or modify
#       it under the terms of the GNU General Public License as published by
#       the Free Software Foundation; either version 2 of the License, or
#       (at your option) any later version.
#
#       This program is distributed in the hope that it will be useful,
#       but WITHOUT ANY WARRANTY; without even the implied warranty of
#       MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#       GNU General Public License for more details.
#
#       You should have received a copy of the GNU General Public License
#       along with this program; if not, write to the Free Software
#       Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston,
#       MA 02110-1301, USA.

import psycopg2
import psycopg2.extras
import psycopg2.errorcodes
import jsonpickle
import cgi
import math
import re
import logging

from pybit.models import Arch,Dist,Format,Status,Suite,BuildD,Job,Package,PackageInstance,SuiteArch,JobHistory, ClientMessage, checkValue, Transport,\
	BuildEnv, BuildEnvSuiteArch,Blacklist

def remove_nasties(nastystring):
	try:
		if isinstance(nastystring, basestring):
			escaped_string = cgi.escape(nastystring,True) # Escapes <, > , &, and "
			#print "Escaped the string " + nastystring + " to " + escaped_string
			return escaped_string
		else:
			#print "Not escaping: " + str(nastystring) + " as it is not a string."
			return nastystring;
	except Exception as e:
		raise Exception("Error escaping string: " + str(nastystring) + str(e))
		return None

class Database(object):

	conn = None

	# CONSTANTs
	limit_low = 5.0
	limit_high = 10.0;

	#<<<<<<<< General database functions >>>>>>>>

	#Constructor, connects on initialisation.

	def __init__(self, settings):
		self.settings = settings
		self.log = logging.getLogger("db" )
		if (('debug' in self.settings) and ( self.settings['debug'])) :
			self.log.setLevel( logging.DEBUG )
		self.log.debug("DB constructor called.")
		self.connect()
	#Deconstructor, disconnects on disposal.
	def __del__(self):
		self.disconnect()

	#Connects to DB using settings loaded from file.
	def connect(self):
		# for catbells
		if (checkValue('password',self.settings)):
			if (checkValue('hostname',self.settings) and checkValue('port',self.settings)):
				# remote with password
				self.log.debug("REMOTE WITH PASSWORD")
				self.conn = psycopg2.connect(database=self.settings['databasename'],
				user=self.settings['user'], host=self.settings['hostname'],
				port=self.settings['port'], password=self.settings['password'])
			else:
				# local with password
				self.log.debug("LOCAL WITH PASSWORD")
				self.conn = psycopg2.connect(database=self.settings['databasename'],
				user=self.settings['user'], password=self.settings['password'])
		else:
			if (checkValue('hostname',self.settings) and checkValue('port',self.settings)):
				# remote without password
				self.log.debug("REMOTE WITHOUT PASSWORD")
				self.conn = psycopg2.connect(database=self.settings['databasename'],user=self.settings['user'], host=self.settings['hostname'],port=self.settings['port'])
			else:
				# local without password
				self.log.debug("LOCAL WITHOUT PASSWORD")
				self.conn = psycopg2.connect(database=self.settings['databasename'],
				user=self.settings['user'])

	#Called by deconstructor
	def disconnect(self):
		try:
			if self.conn:
				self.conn.commit()
				self.conn.close()
			return True
		except psycopg2.Error as e:
			self.conn.rollback()
			raise Exception("Error disconnecting from database. Database error code: "  + str(e.pgcode) + " - Details: " + str(e.pgerror))
			return False

	#<<<<<<<< NEW CODE >>>>>>>>
	def log_buildRequest(self,build_request_obj):
		try:
			cur = self.conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
			cur.execute("INSERT into buildrequest(job,method,uri,vcs_id) VALUES (%s,%s,%s,%s) RETURNING id",(remove_nasties(build_request_obj.job.id),remove_nasties(build_request_obj.transport.method),remove_nasties(build_request_obj.transport.uri),remove_nasties(build_request_obj.transport.vcs_id)))
			res = cur.fetchall()
			self.conn.commit()
			new_id = res[0]['id']
			cur.close()
			return new_id
		except psycopg2.Error as e:
			self.conn.rollback()
			raise Exception("Error logging build. Database error code: "  + str(e.pgcode) + " - Details: " + str(e.pgerror))
			return None

	def get_jobTransportDetails(self, jobid):
		try:
			cur = self.conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
			cur.execute("SELECT * FROM buildrequest WHERE job = %s",(remove_nasties(jobid),))
			res = cur.fetchall()
			self.conn.commit()

			# Get transport details so we can check out the same source to retry a job.
			transport = Transport(None,res[0]['method'],res[0]['uri'],res[0]['vcs_id'])
			cur.close()
			return transport
		except psycopg2.Error as e:
			self.conn.rollback()
			raise Exception("Error logging build. Database error code: "  + str(e.pgcode) + " - Details: " + str(e.pgerror))
			return None

	#<<<<<<<< Lookup table queries >>>>>>>>
	# Do we care about update or delete?

	def count_arches(self):
		try:
			cur = self.conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
			cur.execute("SELECT COUNT(*) FROM arch AS num_arches")
			res = cur.fetchall()
			self.conn.commit()

			cur.close()

			if res[0][0]:
				pages = res[0][0] / self.limit_low;
			else:
				pages = 1

			return math.ceil(pages);
		except psycopg2.Error as e:
			self.conn.rollback()
			raise Exception("Error retrieving arches count. Database error code: "  + str(e.pgcode) + " - Details: " + str(e.pgerror))
			return None

	def get_arches(self,page=None):
		try:
			cur = self.conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
			if page:

				offset = (page -1) * self.limit_low;
				cur.execute("SELECT id,name FROM arch ORDER BY name LIMIT %s OFFSET %s", (self.limit_low,offset,))
			else:
				cur.execute("SELECT id,name FROM arch ORDER BY name")
			res = cur.fetchall()
			self.conn.commit()

			arches = []
			for i in res:
				arches.append(Arch(i['id'],i['name']))
			cur.close()
			return arches
		except psycopg2.Error as e:
			self.conn.rollback()
			raise Exception("Error retrieving arches list. Database error code: "  + str(e.pgcode) + " - Details: " + str(e.pgerror))
			return None

	def get_arch_id(self,arch_id):
		try:
			cur = self.conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
			cur.execute("SELECT id,name FROM arch WHERE id=%s",(arch_id,))
			res = cur.fetchall()
			self.conn.commit()
			arch = Arch(res[0]['id'],res[0]['name'])
			cur.close()
			return arch
		except psycopg2.Error as e:
			self.conn.rollback()
			raise Exception("Error retrieving arch with id:" + str(arch_id) + ". Database error code: "  + str(e.pgcode) + " - Details: " + str(e.pgerror))
			return None


	def get_arch_byname(self,name):
		try:
			cur = self.conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
			cur.execute("SELECT id,name FROM arch WHERE name=%s",(name,))
			res = cur.fetchall()
			self.conn.commit()

			arches = []
			for i in res:
				arches.append(Arch(i['id'],i['name']))
			cur.close()
			return arches
		except psycopg2.Error as e:
			self.conn.rollback()
			raise Exception("Error retrieving arch by name:" + name + ". Database error code: "  + str(e.pgcode) + " - Details: " + str(e.pgerror))
			return None

	def put_arch(self,name):
		try:
			cur = self.conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
			cur.execute("INSERT into arch(name) VALUES (%s) RETURNING id",(remove_nasties(name),))
			res = cur.fetchall()
			self.conn.commit()
			arch = Arch(res[0]['id'],name)
			cur.close()
			return arch
		except psycopg2.Error as e:
			self.conn.rollback()
			raise Exception("Error adding arch:" + name + ". Database error code: "  + str(e.pgcode) + " - Details: " + str(e.pgerror))
			return None

	def delete_arch(self,arch_id):
		try:
			cur = self.conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
			cur.execute("DELETE FROM arch WHERE id=%s RETURNING id",(arch_id,))
			res = cur.fetchall()
			self.conn.commit()

			if res[0]['id'] == arch_id:
				cur.close()
				return True
			else:
				cur.close()
				return False
		except psycopg2.Error as e:
			self.conn.rollback()
			self.log.debug("Error deleting arch with id: %s. Database error code: %s - Details: %s.",str(arch_id),str(e.pgcode),str(e.pgerror))
			return e.pgcode

	def count_suitearches(self):
		try:
			cur = self.conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
			cur.execute("SELECT COUNT(*) FROM suitearches AS num_suitearches")
			res = cur.fetchall()
			self.conn.commit()

			cur.close()

			if res[0][0]:
				pages = res[0][0] / self.limit_low;
			else:
				pages = 1

			return math.ceil(pages);
		except psycopg2.Error as e:
			self.conn.rollback()
			raise Exception("Error retrieving suitearches count. Database error code: "  + str(e.pgcode) + " - Details: " + str(e.pgerror))
			return None

	def get_suitearches(self):
		try:
			cur = self.conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
			cur.execute("SELECT id,suite_id,arch_id,master_weight FROM suitearches ORDER BY master_weight DESC")
			res = cur.fetchall()
			self.conn.commit()

			suite_arches = []
			for i in res:
				suite_arches.append(SuiteArch(i['id'],self.get_suite_id(i['suite_id']),self.get_arch_id(i['arch_id']),i['master_weight']))
			cur.close()
			return suite_arches
		except psycopg2.Error as e:
			self.conn.rollback()
			raise Exception("Error retrieving suite arches list. Database error code: "  + str(e.pgcode) + " - Details: " + str(e.pgerror))
			return None

	def get_suitearch_id(self,suitearch_id):
		try:
			cur = self.conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
			cur.execute("SELECT id,suite_id,arch_id,master_weight FROM suitearches WHERE id=%s",(suitearch_id,))
			res = cur.fetchall()
			self.conn.commit()
			suitearch = SuiteArch(res[0]['id'],self.get_suite_id(res[0]['suite_id']),self.get_arch_id(res[0]['arch_id']),res[0]['master_weight'])
			cur.close()
			return suitearch
		except psycopg2.Error as e:
			self.conn.rollback()
			raise Exception("Error retrieving suite arch with id:" + str(suitearch_id) + ". Database error code: "  + str(e.pgcode) + " - Details: " + str(e.pgerror))
			return None

	def get_suitearch_by_suite_name(self,suite,arch):
		try:
			cur = self.conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
			cur.execute("SELECT id,suite_id,arch_id,master_weight FROM suitearches WHERE suite.id=%s, arch.id=%s",(suite.id,arch.id))
			res = cur.fetchall()
			self.conn.commit()
			suitearch = SuiteArch(res[0]['id'],self.get_suite_id(res[0]['suite_id']),self.get_arch_id(res[0]['arch_id']),res[0]['master_weight'])
			cur.close()
			return suitearch
		except psycopg2.Error as e:
			self.conn.rollback()
			raise Exception("Error retrieving suite arch with suite and arch:. Database error code: "  + str(e.pgcode) + " - Details: " + str(e.pgerror))
			return None

	def put_suitearch(self,suite_id,arch_id,master_weight = 0):
		try:
			cur = self.conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
			cur.execute("INSERT into suitearches(suite_id,arch_id,master_weight) VALUES (%s, %s, %s) RETURNING id",(remove_nasties(suite_id),remove_nasties(arch_id),remove_nasties(master_weight)))
			res = cur.fetchall()
			self.conn.commit()
			suitearch = SuiteArch(res[0]['id'],self.get_suite_id(suite_id),self.get_arch_id(arch_id),master_weight)
			cur.close()
			return suitearch
		except psycopg2.Error as e:
			self.conn.rollback()
			raise Exception("Error adding suite arch:" + suite_id + arch_id + ". Database error code: "  + str(e.pgcode) + " - Details: " + str(e.pgerror))
			return None

	def delete_suitearch(self,suitearch_id):
		try:
			cur = self.conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
			cur.execute("DELETE FROM suitearches WHERE id=%s RETURNING id",(suitearch_id,))
			res = cur.fetchall()
			self.conn.commit()

			if res[0]['id'] == suitearch_id:
				cur.close()
				return True
			else:
				cur.close()
				return False
		except psycopg2.Error as e:
			self.conn.rollback()
			self.log.debug("Error deleting suitearch with id: %s. Database error code: %s - Details: %s.",str(suitearch_id),str(e.pgcode),str(e.pgerror))
			return e.pgcode

	def count_buildenv_suitearches(self):
		try:
			cur = self.conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
			cur.execute("SELECT COUNT(*) FROM buildenvsuitearch AS num_buildenv_suitearches")
			res = cur.fetchall()
			self.conn.commit()

			cur.close()

			if res[0][0]:
				pages = res[0][0] / self.limit_low;
			else:
				pages = 1

			return math.ceil(pages);
		except psycopg2.Error as e:
			self.conn.rollback()
			raise Exception("Error retrieving buildenv suitearch count. Database error code: "  + str(e.pgcode) + " - Details: " + str(e.pgerror))
			return None

	def get_buildenv_suitearches(self):
		try:
			cur = self.conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
			cur.execute("SELECT id,buildenv_id,suitearch_id FROM buildenvsuitearch")
			res = cur.fetchall()
			self.conn.commit()

			buildenv_suitearches = []
			for i in res:
				buildenv_suitearches.append(BuildEnvSuiteArch(i['id'],self.get_build_env_id(i['buildenv_id']),self.get_suitearch_id(i['suitearch_id'])))
			cur.close()
			return buildenv_suitearches
		except psycopg2.Error as e:
			self.conn.rollback()
			raise Exception("Error retrieving buildenv suitearch list. Database error code: "  + str(e.pgcode) + " - Details: " + str(e.pgerror))
			return None

	def get_buildenv_suitearch_id(self,buildenv_suitearch_id):
		try:
			cur = self.conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
			cur.execute("SELECT id,buildenv_id,suitearch_id FROM buildenvsuitearch WHERE id=%s",(buildenv_suitearch_id,))
			res = cur.fetchall()
			self.conn.commit()
			buildenv_suitearch = BuildEnvSuiteArch(res[0]['id'],self.get_build_env_id(res[0]['buildenv_id']),self.get_suitearch_id(res[0]['suitearch_id']))
			cur.close()
			return buildenv_suitearch
		except psycopg2.Error as e:
			self.conn.rollback()
			raise Exception("Error retrieving buildenv suitearch with id:" + str(buildenv_suitearch_id) + ". Database error code: "  + str(e.pgcode) + " - Details: " + str(e.pgerror))
			return None


	def put_buildenv_suitearch(self,buildenv_id,suitearch_id):
		try:
			cur = self.conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
			cur.execute("INSERT into buildenvsuitearch(buildenv_id,suitearch_id) VALUES (%s, %s) RETURNING id",(remove_nasties(buildenv_id),remove_nasties(suitearch_id)))
			res = cur.fetchall()
			self.conn.commit()
			buildenv_suitearch = BuildEnvSuiteArch(res[0]['id'],self.get_build_env_id(buildenv_id),self.get_suitearch_id(suitearch_id))
			cur.close()
			return buildenv_suitearch
		except psycopg2.Error as e:
			self.conn.rollback()
			raise Exception("Error adding buildenv suitearch:" + buildenv_id + suitearch_id + ". Database error code: "  + str(e.pgcode) + " - Details: " + str(e.pgerror))
			return None

	def delete_buildenv_suitearch(self,buildenv_suitearch_id):
		try:
			cur = self.conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
			cur.execute("DELETE FROM buildenvsuitearch WHERE id=%s RETURNING id",(buildenv_suitearch_id,))
			res = cur.fetchall()
			self.conn.commit()

			if res[0]['id'] == buildenv_suitearch_id:
				cur.close()
				return True
			else:
				cur.close()
				return False
		except psycopg2.Error as e:
			self.conn.rollback()
			self.log.debug("Error deleting buildenvsuitearch with id: %s. Database error code: %s - Details: %s.",str(buildenv_suitearch_id),str(e.pgcode),str(e.pgerror))
			return e.pgcode

	def count_dists(self):
		try:
			cur = self.conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
			cur.execute("SELECT COUNT(*) FROM distribution AS num_dists")
			res = cur.fetchall()
			self.conn.commit()

			cur.close()

			if res[0][0]:
				pages = res[0][0] / self.limit_low;
			else:
				pages = 1

			return math.ceil(pages);
		except psycopg2.Error as e:
			self.conn.rollback()
			raise Exception("Error retrieving distributions count. Database error code: "  + str(e.pgcode) + " - Details: " + str(e.pgerror))
			return None

	def get_dists(self,page=None):
		try:
			cur = self.conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
			if page:

				offset = (page -1) * self.limit_low;
				cur.execute("SELECT id,name FROM distribution ORDER BY name LIMIT %s OFFSET %s", (self.limit_low,offset,))
			else:
				cur.execute("SELECT id,name FROM distribution ORDER BY name")
			res = cur.fetchall()
			self.conn.commit()

			dists = []
			for i in res:
				dists.append(Dist(i['id'],i['name']))
			cur.close()
			return dists
		except psycopg2.Error as e:
			self.conn.rollback()
			raise Exception("Error retrieving dist list. Database error code: "  + str(e.pgcode) + " - Details: " + str(e.pgerror))
			return None

	def get_dist_id(self,dist_id):
		try:
			cur = self.conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
			cur.execute("SELECT id,name FROM distribution WHERE id=%s",(dist_id,))
			res = cur.fetchall()
			self.conn.commit()
			dist = Dist(res[0]['id'],res[0]['name'])
			cur.close()
			return dist
		except psycopg2.Error as e:
			self.conn.rollback()
			raise Exception("Error retrieving dist with id:" + str(dist_id) + ". Database error code: "  + str(e.pgcode) + " - Details: " + str(e.pgerror))
			return None


	def get_dist_byname(self,name):
		try:
			cur = self.conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
			cur.execute("SELECT id,name FROM distribution WHERE name=%s",(name,))
			res = cur.fetchall()
			self.conn.commit()

			dists = []
			for i in res:
				dists.append(Dist(i['id'],i['name']))
			cur.close()
			return dists
		except psycopg2.Error as e:
			self.conn.rollback()
			raise Exception("Error retrieving dist by name:" + name + ". Database error code: "  + str(e.pgcode) + " - Details: " + str(e.pgerror))
			return None

	def put_dist(self,name):
		try:
			cur = self.conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
			cur.execute("INSERT into distribution(name) VALUES (%s)  RETURNING id",(remove_nasties(name),))
			res = cur.fetchall()
			self.conn.commit()
			dist = Dist(res[0]['id'],name)
			cur.close()
			return dist
		except psycopg2.Error as e:
			self.conn.rollback()
			raise Exception("Error adding dist:" + name + ". Database error code: "  + str(e.pgcode) + " - Details: " + str(e.pgerror))
			return None

	def delete_dist(self,dist_id):
		try:
			cur = self.conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
			cur.execute("DELETE FROM distribution WHERE id=%s RETURNING id",(dist_id,))
			res = cur.fetchall()
			self.conn.commit()

			if res[0]['id'] == dist_id:
				cur.close()
				return True
			else:
				cur.close()
				return False
		except psycopg2.Error as e:
			self.conn.rollback()
			self.log.debug("Error deleting dist with id: %s. Database error code: %s - Details: %s.",str(dist_id),str(e.pgcode),str(e.pgerror))
			return e.pgcode

	def count_formats(self):
		try:
			cur = self.conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
			cur.execute("SELECT COUNT(*) FROM format AS num_formats")
			res = cur.fetchall()
			self.conn.commit()

			cur.close()

			if res[0][0]:
				pages = res[0][0] / self.limit_low;
			else:
				pages = 1

			return math.ceil(pages);
		except psycopg2.Error as e:
			self.conn.rollback()
			raise Exception("Error retrieving formats count. Database error code: "  + str(e.pgcode) + " - Details: " + str(e.pgerror))
			return None


	def get_formats(self,page=None):
		try:
			cur = self.conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
			if page:

				offset = (page -1) * self.limit_low;
				cur.execute("SELECT id,name FROM format ORDER BY name LIMIT %s OFFSET %s", (self.limit_low,offset,))
			else:
				cur.execute("SELECT id,name FROM format ORDER BY name")
			res = cur.fetchall()
			self.conn.commit()

			formats = []
			for i in res:
				formats.append(Format(i['id'],i['name']))
			cur.close()
			return formats
		except psycopg2.Error as e:
			self.conn.rollback()
			raise Exception("Error retrieving formats list. Database error code: "  + str(e.pgcode) + " - Details: " + str(e.pgerror))
			return None

	def get_format_id(self,format_id):
		try:
			cur = self.conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
			cur.execute("SELECT id,name FROM format WHERE id=%s",(format_id,))
			res = cur.fetchall()
			self.conn.commit()
			ret_format = Format(res[0]['id'],res[0]['name'])
			cur.close()
			return  ret_format
		except psycopg2.Error as e:
			self.conn.rollback()
			raise Exception("Error retrieving format with id:" + str(format_id) + ". Database error code: "  + str(e.pgcode) + " - Details: " + str(e.pgerror))
			return None


	def get_format_byname(self,name):
		try:
			cur = self.conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
			cur.execute("SELECT id,name FROM format WHERE name=%s",(name,))
			res = cur.fetchall()

			formats = []
			for i in res:
				formats.append(Format(i['id'],i['name']))
			cur.close()
			return formats
		except psycopg2.Error as e:
			raise Exception("Error retrieving format by name:" + name + ". Database error code: "  + str(e.pgcode) + " - Details: " + str(e.pgerror))
			return None

	def put_format(self,name):
		try:
			cur = self.conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
			cur.execute("INSERT into format(name) VALUES (%s)  RETURNING id",(remove_nasties(name),))
			res = cur.fetchall()
			self.conn.commit()
			ret_format = Format(res[0]['id'],name)
			cur.close()
			return ret_format
		except psycopg2.Error as e:
			self.conn.rollback()
			raise Exception("Error adding format:" + name + ". Database error code: "  + str(e.pgcode) + " - Details: " + str(e.pgerror))
			return None

	def delete_format(self,format_id):
		try:
			cur = self.conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
			cur.execute("DELETE FROM format WHERE id=%s RETURNING id",(format_id,))
			res = cur.fetchall()
			self.conn.commit()

			if res[0]['id'] == format_id:
				cur.close()
				return True
			else:
				cur.close()
				return False
		except psycopg2.Error as e:
			self.conn.rollback()
			self.log.debug("Error deleting format with id: %s. Database error code: %s - Details: %s.",str(format_id),str(e.pgcode),str(e.pgerror))
			return e.pgcode

	def count_statuses(self):
		try:
			cur = self.conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
			cur.execute("SELECT COUNT(*) FROM status AS num_statuses")
			res = cur.fetchall()
			self.conn.commit()

			cur.close()

			if res[0][0]:
				pages = res[0][0] / self.limit_low;
			else:
				pages = 1

			return math.ceil(pages); # ALWAYS round up.
		except psycopg2.Error as e:
			self.conn.rollback()
			raise Exception("Error retrieving statuses count. Database error code: "  + str(e.pgcode) + " - Details: " + str(e.pgerror))
			return None

	def get_statuses(self,page=None):
		try:
			cur = self.conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
			if page:

				offset = (page -1) * self.limit_low;
				cur.execute("SELECT id,name FROM status ORDER BY name LIMIT %s OFFSET %s", (self.limit_low,offset,))
			else:
				cur.execute("SELECT id,name FROM status ORDER BY name")
			res = cur.fetchall()
			self.conn.commit()

			statuses = []
			for i in res:
				statuses.append(Status(i['id'],i['name']))
			cur.close()
			return statuses
		except psycopg2.Error as e:
			self.conn.rollback()
			raise Exception("Error retrieving status list. Database error code: "  + str(e.pgcode) + " - Details: " + str(e.pgerror))
			return None

	def get_status_id(self,status_id):
		try:
			cur = self.conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
			cur.execute("SELECT id,name FROM status WHERE id=%s",(status_id,))
			res = cur.fetchall()
			self.conn.commit()
			status = Status(res[0]['id'],res[0]['name'])
			cur.close()
			return status
		except psycopg2.Error as e:
			self.conn.rollback()
			raise Exception("Error retrieving status with id:" + str(status_id) + ". Database error code: "  + str(e.pgcode) + " - Details: " + str(e.pgerror))
			return None

	def put_status(self,name):
		try:
			cur = self.conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
			cur.execute("INSERT into status(name) VALUES (%s)  RETURNING id",(remove_nasties(name),))
			res = cur.fetchall()
			self.conn.commit()
			status = Status(res[0]['id'],name)
			cur.close()
			return status
		except psycopg2.Error as e:
			self.conn.rollback()
			raise Exception("Error add status:" + name + ". Database error code: "  + str(e.pgcode) + " - Details: " + str(e.pgerror))
			return None

	def delete_status(self,status_id):
		try:
			cur = self.conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
			cur.execute("DELETE FROM status WHERE id=%s RETURNING id",(status_id,))
			res = cur.fetchall()
			self.conn.commit()

			if res[0]['id'] == status_id:
				cur.close()
				return True
			else:
				cur.cloes()
				return False
		except psycopg2.Error as e:
			self.conn.rollback()
			self.log.debug("Error deleting status with id: %s. Database error code: %s - Details: %s.",str(status_id),str(e.pgcode),str(e.pgerror))
			return e.pgcode

	def count_suites(self):
		try:
			cur = self.conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
			cur.execute("SELECT COUNT(*) FROM suite AS num_suites")
			res = cur.fetchall()
			self.conn.commit()

			cur.close()

			if res[0][0]:
				pages = res[0][0] / self.limit_low;
			else:
				pages = 1

			return math.ceil(pages);
		except psycopg2.Error as e:
			self.conn.rollback()
			raise Exception("Error retrieving suites count. Database error code: "  + str(e.pgcode) + " - Details: " + str(e.pgerror))
			return None

	def get_suites(self,page=None):
		try:
			cur = self.conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
			if page:

				offset = (page -1) * self.limit_low;
				cur.execute("SELECT id,name FROM suite ORDER BY name LIMIT %s OFFSET %s", (self.limit_low,offset,))
			else:
				cur.execute("SELECT id,name FROM suite ORDER BY name")
			res = cur.fetchall()
			self.conn.commit()

			suites = []
			for i in res:
				suites.append(Suite(i['id'],i['name']))
			cur.close()
			return suites
		except psycopg2.Error as e:
			self.conn.rollback()
			raise Exception("Error retrieving suite list. Database error code: "  + str(e.pgcode) + " - Details: " + str(e.pgerror))
			return None

	def get_suite_id(self,suite_id):
		try:
			cur = self.conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
			cur.execute("SELECT id,name FROM suite WHERE id=%s",(suite_id,))
			res = cur.fetchall()
			self.conn.commit()
			suite = Suite(res[0]['id'],res[0]['name'])
			cur.close()
			return suite
		except psycopg2.Error as e:
			self.conn.rollback()
			raise Exception("Error retrieving suite with id:" + str(suite_id) + ". Database error code: "  + str(e.pgcode) + " - Details: " + str(e.pgerror))
			return None


	def get_suite_byname(self,name):
		try:
			cur = self.conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
			cur.execute("SELECT id,name FROM suite WHERE name=%s",(name,))
			res = cur.fetchall()
			self.conn.commit()

			suites = []
			for i in res:
				suites.append(Suite(i['id'],i['name']))
			cur.close()
			return suites
		except psycopg2.Error as e:
			self.conn.rollback()
			raise Exception("Error retrieving suite with name:" + name + ". Database error code: "  + str(e.pgcode) + " - Details: " + str(e.pgerror))
			return None

	def put_suite(self,name):
		try:
			cur = self.conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
			cur.execute("INSERT into suite(name) VALUES (%s)  RETURNING id",(remove_nasties(name),))
			res = cur.fetchall()
			self.conn.commit()
			suite = Suite(res[0]['id'],name)
			cur.close()
			return suite
		except psycopg2.Error as e:
			self.conn.rollback()
			raise Exception("Error adding suite:" + name + ". Database error code: "  + str(e.pgcode) + " - Details: " + str(e.pgerror))
			return None

	def delete_suite(self,suite_id):
		try:
			cur = self.conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
			cur.execute("DELETE FROM suite WHERE id=%s RETURNING id",(suite_id,))
			res = cur.fetchall()
			self.conn.commit()

			if res[0]['id'] == suite_id:
				cur.close()
				return True
			else:
				cur.close()
				return False
		except psycopg2.Error as e:
			self.conn.rollback()
			self.log.debug("Error deleting suite with id: %s. Database error code: %s - Details: %s.",str(suite_id),str(e.pgcode),str(e.pgerror))
			return e.pgcode

	def count_build_envs(self):
		try:
			cur = self.conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
			cur.execute("SELECT COUNT(*) FROM buildenv AS num_build_envs")
			res = cur.fetchall()
			self.conn.commit()

			cur.close()
			if res[0][0]:
				pages = res[0][0] / self.limit_low;
			else:
				pages = 1

			return math.ceil(pages);
		except psycopg2.Error as e:
			self.conn.rollback()
			raise Exception("Error retrieving buildenv count. Database error code: "  + str(e.pgcode) + " - Details: " + str(e.pgerror))
			return None

	def get_build_envs(self,page=None):
		try:
			cur = self.conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
			if page:

				offset = (page -1) * self.limit_low;
				cur.execute("SELECT id,name FROM buildenv ORDER BY name LIMIT %s OFFSET %s", (self.limit_low,offset,))
			else:
				cur.execute("SELECT id,name FROM buildenv ORDER BY name")
			res = cur.fetchall()
			self.conn.commit()

			build_envs = []
			for i in res:
				build_envs.append(BuildEnv(i['id'],i['name']))
			cur.close()
			return build_envs
		except psycopg2.Error as e:
			self.conn.rollback()
			raise Exception("Error retrieving buildenv list. Database error code: "  + str(e.pgcode) + " - Details: " + str(e.pgerror))
			return None

	def get_build_env_id(self,build_env_id):
		try:
			cur = self.conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
			cur.execute("SELECT id,name FROM buildenv WHERE id=%s",(build_env_id,))
			res = cur.fetchall()
			self.conn.commit()

			if res:
				build_env = BuildEnv(res[0]['id'],res[0]['name'])
			else:
				build_env = None

			cur.close()
			return build_env
		except psycopg2.Error as e:
			self.conn.rollback()
			raise Exception("Error retrieving buildenv with id:" + str(build_env_id) + ". Database error code: "  + str(e.pgcode) + " - Details: " + str(e.pgerror))
			return None

	def get_build_env_byname(self,name):
		try:
			cur = self.conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
			cur.execute("SELECT id,name FROM buildenv WHERE name=%s",(name,))
			res = cur.fetchall()
			self.conn.commit()

			build_envs = []
			for i in res:
				build_envs.append(BuildEnv(i['id'],i['name']))
			cur.close()
			return build_envs
		except psycopg2.Error as e:
			self.conn.rollback()
			raise Exception("Error retrieving buildenv with name:" + name + ". Database error code: "  + str(e.pgcode) + " - Details: " + str(e.pgerror))
			return None

	def put_build_env(self,name):
		try:
			cur = self.conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
			cur.execute("INSERT INTO buildenv(name) VALUES (%s)  RETURNING id",(remove_nasties(name),))
			res = cur.fetchall()
			self.conn.commit()
			build_env = BuildEnv(res[0]['id'],name)
			cur.close()
			return build_env
		except psycopg2.Error as e:
			self.conn.rollback()
			raise Exception("Error adding build_env:" + name + ". Database error code: "  + str(e.pgcode) + " - Details: " + str(e.pgerror))
			return None

	def delete_build_env(self,build_env_id):
		try:
			cur = self.conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
			cur.execute("DELETE FROM buildenv WHERE id=%s RETURNING id",(build_env_id,))
			res = cur.fetchall()
			self.conn.commit()

			if res[0]['id'] == build_env_id:
				cur.close()
				return True
			else:
				cur.close()
				return False
		except psycopg2.Error as e:
			self.conn.rollback()
			self.log.debug("Error deleting buildenv with id: %s. Database error code: %s - Details: %s.",str(build_env_id),str(e.pgcode),str(e.pgerror))
			return e.pgcode

	#<<<<<<<< BuildD related database functions >>>>>>>>

	def count_buildclients(self):
		try:
			cur = self.conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
			cur.execute("SELECT COUNT(*) FROM buildclients AS num_buildclients")
			res = cur.fetchall()
			self.conn.commit()

			cur.close()

			if res[0][0]:
				pages = res[0][0] / self.limit_high;
			else:
				pages = 1

			return math.ceil(pages);
		except psycopg2.Error as e:
			self.conn.rollback()
			raise Exception("Error retrieving buildclients count. Database error code: "  + str(e.pgcode) + " - Details: " + str(e.pgerror))
			return None

	def get_buildclients(self,page=None):
		try:
			cur = self.conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
			if page:
				# CONSTANT
				offset = (page -1) * self.limit_high;
				cur.execute("SELECT id,name FROM buildclients ORDER BY name LIMIT %s OFFSET %s", (self.limit_high,offset,))
			else:
				cur.execute("SELECT id,name FROM buildclients ORDER BY name")
			res = cur.fetchall()
			self.conn.commit()

			build_clients = []
			for i in res:
				build_clients.append(BuildD(i['id'],i['name']))
			cur.close()
			return build_clients
		except psycopg2.Error as e:
			self.conn.rollback()
			raise Exception("Error retrieving buildd list. Database error code: "  + str(e.pgcode) + " - Details: " + str(e.pgerror))
			return None

	def get_buildd_id(self,buildd_id):
		try:
			cur = self.conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
			cur.execute("SELECT id,name FROM buildclients WHERE id=%s",(buildd_id,))
			res = cur.fetchall()
			self.conn.commit()
			if (res):
				buildd = BuildD(res[0]['id'],res[0]['name'])
				cur.close()
				return buildd
			else:
				return None
		except psycopg2.Error as e:
			self.conn.rollback()
			raise Exception("Error retrieving buildd with id:" + str(buildd_id) + ". Database error code: "  + str(e.pgcode) + " - Details: " + str(e.pgerror))
			return None

	def put_buildclient(self,name):
		try:
			cur = self.conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
			cur.execute("INSERT into buildclients(name) VALUES (%s)  RETURNING id",(remove_nasties(name),))
			res = cur.fetchall()
			self.conn.commit()
			buildd = BuildD(res[0]['id'],name)
			cur.close()
			return buildd
		except psycopg2.Error as e:
			self.conn.rollback()
			raise Exception("Error adding buildd:" + name + ". Database error code: "  + str(e.pgcode) + " - Details: " + str(e.pgerror))
			return None

	def delete_buildclient(self,buildclient_id):
		try:
			cur = self.conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
			cur.execute("DELETE FROM buildclients WHERE id=%s RETURNING id",(buildclient_id,))
			res = cur.fetchall()
			self.conn.commit()

			if res[0]['id'] == buildclient_id:
				cur.close()
				return True
			else:
				cur.close()
				return False
		except psycopg2.Error as e:
			self.conn.rollback()
			self.log.debug("Error deleting buildd with id: %s. Database error code: %s - Details: %s.",str(buildclient_id),str(e.pgcode),str(e.pgerror))
			return e.pgcode

	def get_buildd_jobs(self,buildclient_id):
		try:
			cur = self.conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
			cur.execute("SELECT job.id AS job_id,packageinstance_id,buildclients.id AS buildclients_id FROM buildclients,job WHERE buildclients.id=%s AND buildclients.id = job.buildclient_id  ORDER BY job.id",(buildclient_id,))
			res = cur.fetchall()
			self.conn.commit()

			jobs = []
			for i in res:
				packageinstance = self.get_packageinstance_id(i['packageinstance_id'])
				jobs.append(Job(i['job_id'],packageinstance,buildclient_id))
			cur.close()
			return jobs
		except psycopg2.Error as e:
			self.conn.rollback()
			raise Exception("Error retrieving jobs on buildd with id:" + str(buildclient_id) + ". Database error code: "  + str(e.pgcode) + " - Details: " + str(e.pgerror))
			return None

	#<<<<<<<< Job related database functions >>>>>>>>
	# UPDATE queries?

	def get_job(self,job_id):
		try:
			cur = self.conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
			cur.execute("SELECT id,packageinstance_id,buildclient_id FROM job WHERE id=%s",(job_id,))
			res = cur.fetchall()
			self.conn.commit()

			packageinstance = self.get_packageinstance_id(res[0]['packageinstance_id'])
			buildclient = self.get_buildd_id(res[0]['buildclient_id']) if res[0]['buildclient_id'] else None
			job = Job(res[0]['id'],packageinstance,buildclient)
			cur.close()
			return job
		except psycopg2.Error as e:
			self.conn.rollback()
			raise Exception("Error retrieving job with id:" + str(job_id) + ". Database error code: "  + str(e.pgcode) + " - Details: " + str(e.pgerror))
			return None

	def get_jobs(self,page=None):
		try:
			cur = self.conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
			if page:
				# CONSTANT
				offset = (page -1) * self.limit_high;
				cur.execute("SELECT id,packageinstance_id,buildclient_id FROM job ORDER BY id LIMIT %s OFFSET %s", (self.limit_high,offset,))
			else:
				cur.execute("SELECT id,packageinstance_id,buildclient_id FROM job ORDER BY id")
			res = cur.fetchall()
			self.conn.commit()

			jobs = []
			for i in res:
				packageinstance = self.get_packageinstance_id(i['packageinstance_id'])
				buildclient = self.get_buildd_id(i['buildclient_id']) if i['buildclient_id'] else None
				jobs.append(Job(i['id'],packageinstance,buildclient))
			cur.close()
			return jobs
		except psycopg2.Error as e:
			self.conn.rollback()
			raise Exception("Error retrieving jobs list. Database error code: "  + str(e.pgcode) + " - Details: " + str(e.pgerror))
			return None

	def get_jobs_by_status(self,status):
		try:
			cur = self.conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
			cur.execute("WITH latest_status AS (SELECT DISTINCT ON (job_id) job_id, status.name FROM jobstatus LEFT JOIN status ON status_id=status.id ORDER BY job_id, time DESC) SELECT job_id, name FROM latest_status WHERE name=%s",(status,));
			res = cur.fetchall()
			self.conn.commit()

			jobs = []
			for i in res:
				jobs.append(self.get_job(i['job_id']))
			cur.close()
			return jobs
		except psycopg2.Error as e:
			self.conn.rollback()
			raise Exception("Error retrieving jobs list with status:" + status + ". Database error code: "  + str(e.pgcode) + " - Details: " + str(e.pgerror))
			return None

	def get_unfinished_jobs(self):
		try:
			cur = self.conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
			cur.execute("WITH latest_status AS (SELECT DISTINCT ON (job_id) job_id, status.name FROM jobstatus LEFT JOIN status ON status_id=status.id ORDER BY job_id, time DESC) SELECT job_id, name FROM latest_status WHERE name!='Uploaded' AND name!='Done' AND name!='Cancelled' ORDER BY job_id");
			res = cur.fetchall()
			self.conn.commit()

			jobs = []
			for i in res:
				jobs.append(self.get_job(i['job_id']))
			cur.close()
			return jobs

		except psycopg2.Error as e:
			self.conn.rollback()
			raise Exception("Error retrieving unfinished jobs. Database error code: "  + str(e.pgcode) + " - Details: " + str(e.pgerror))
			return None

	def get_job_statuses(self,job_id):
	#gets job status *history*
		try:
			cur = self.conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
			cur.execute("SELECT job.id AS job_id, status.name AS status, buildclients.name AS buildclient, jobstatus.time AS time FROM job LEFT JOIN jobstatus ON job.id=jobstatus.job_id LEFT JOIN status ON jobstatus.status_id=status.id  LEFT JOIN buildclients ON buildclients.id=job.buildclient_id WHERE job.id = %s ORDER BY time",(job_id,));
			res = cur.fetchall()
			self.conn.commit()
			jobstatuses = []
			for i in res:
				jobstatuses.append(JobHistory(i['job_id'],i['status'],i['buildclient'],i['time']))
			cur.close()
			return jobstatuses
		except psycopg2.Error as e:
			self.conn.rollback()
			raise Exception("Error retrieving job status with:" + str(job_id) + ". Database error code: "  + str(e.pgcode) + " - Details: " + str(e.pgerror))
			return None

	def put_job_status(self, jobid, status, client=None):
		try:
			self.log.debug("put_job_status: %s %s %s", jobid, status, client)
			cur = self.conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
			cur.execute("INSERT INTO jobstatus (job_id, status_id) VALUES (%s, (SELECT id FROM status WHERE name=%s))",
					 (remove_nasties(jobid),remove_nasties(status),))
			if client is not None and client != "":
				#insert the client if it doesn't already exist.
				cur.execute("INSERT INTO buildclients(name) SELECT name FROM buildclients UNION VALUES(%s) EXCEPT SELECT name FROM buildclients",
						(remove_nasties(client),))

				cur.execute("UPDATE job SET buildclient_id=(SELECT id FROM buildclients WHERE name=%s) WHERE id=%s",
						 (remove_nasties(client),remove_nasties(jobid)))
			self.conn.commit()
			cur.close()
		except psycopg2.Error as e:
			self.conn.rollback()
			raise Exception("Error setting job status. Database error code: "  + str(e.pgcode) + " - Details: " + str(e.pgerror))
			return None

	def delete_job(self,job_id):
		try:
			cur = self.conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
			cur.execute("WITH latest_status AS (SELECT DISTINCT ON (job_id) job_id, status.name FROM jobstatus LEFT JOIN status ON status_id=status.id WHERE job_id=%s ORDER BY job_id, time DESC) SELECT job_id, name FROM latest_status WHERE name!='Building'",(job_id,))
			res = cur.fetchall()
			self.conn.commit()
			if len(res) > 0:
				cur.execute("DELETE FROM jobstatus WHERE job_id=%s RETURNING id",(job_id,))
				self.conn.commit()
				cur.execute("DELETE FROM job WHERE id=%s  RETURNING id",(job_id,))
				res = cur.fetchall()
				self.conn.commit()
				if res[0]['id'] == job_id:
					cur.close()
					return True
				else:
					cur.close()
					return False
			else:
				cur.close()
				return False
		except psycopg2.Error as e:
			self.conn.rollback()
			self.log.debug("Error deleting job with id: %s. Database error code: %s - Details: %s.",str(job_id),str(e.pgcode),str(e.pgerror))
			return e.pgcode

	def put_job(self,packageinstance,buildclient):
		try:
			if buildclient:
				buildclient_id = remove_nasties(buildclient.id)
			else:
				buildclient_id = None

			cur = self.conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
			cur.execute("INSERT INTO job (packageinstance_id,buildclient_id) VALUES (%s, %s)  RETURNING id",(remove_nasties(packageinstance.id),(buildclient_id)))
			res = cur.fetchall()

			job_id = res[0]['id']
			if job_id is not None:
				cur.execute("INSERT INTO jobstatus (job_id, status_id) VALUES (%s, (SELECT id FROM status WHERE status.name=%s))",
					(remove_nasties(job_id), remove_nasties(ClientMessage.waiting)))
				self.conn.commit()
			else:
				self.conn.rollback()

			job =  Job(job_id,packageinstance,buildclient)
			cur.close()
			return job
		except psycopg2.Error as e:
			self.conn.rollback()
			raise Exception("Error adding job. Database error code: " + str(e.pgcode) + " - Details: " + str(e.pgerror))
			return None

	#<<<<<<<< Package related database functions >>>>>>>>
	# UPDATE queries?

	def count_packages(self):
		try:
			cur = self.conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
			cur.execute("SELECT COUNT(*) FROM package AS num_packages")
			res = cur.fetchall()
			self.conn.commit()

			cur.close()

			if res[0][0]:
				pages = res[0][0] / self.limit_high;
			else:
				pages = 1

			return math.ceil(pages);
		except psycopg2.Error as e:
			self.conn.rollback()
			raise Exception("Error retrieving packages count. Database error code: "  + str(e.pgcode) + " - Details: " + str(e.pgerror))
			return None

	def get_packages(self,page=None):
		try:
			cur = self.conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
			if page:
				# CONSTANT
				offset = (page -1) * self.limit_high;
				cur.execute("SELECT id,version,name FROM package ORDER BY name,id LIMIT %s OFFSET %s", (self.limit_high,offset,))
			else:
				cur.execute("SELECT id,version,name FROM package ORDER BY name,id")
			res = cur.fetchall()
			self.conn.commit()

			packages = []
			for i in res:
				packages.append(Package(i['id'],i['version'],i['name']))
			cur.close()
			return packages
		except psycopg2.Error as e:
			self.conn.rollback()
			raise Exception("Error retrieving packages list. Database error code: "  + str(e.pgcode) + " - Details: " + str(e.pgerror))
			return None

	def get_packagenames(self):
		try:
			cur = self.conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
			cur.execute("SELECT DISTINCT (name), name FROM package GROUP BY name ORDER BY name") # We only care about a unique list of names
			res = cur.fetchall()
			self.conn.commit()

			packages = []
			for i in res:
				packages.append(Package(None,None,i['name'])) # TODO: these may actually be useful to have still.
			cur.close()
			return packages
		except psycopg2.Error as e:
			self.conn.rollback()
			raise Exception("Error retrieving packages list. Database error code: "  + str(e.pgcode) + " - Details: " + str(e.pgerror))
			return None

	def get_packages_byname(self, name):
		try:
			cur = self.conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
			cur.execute("SELECT id,version,name FROM package WHERE name=%s",(name,))
			res = cur.fetchall()
			self.conn.commit()

			packages = []
			for i in res:
				packages.append(Package(i['id'],i['version'],i['name']))
			cur.close()
			return packages
		except psycopg2.Error as e:
			self.conn.rollback()
			raise Exception("Error retrieving package with name:" + str(name) + ". Database error code: "  + str(e.pgcode) + " - Details: " + str(e.pgerror))
			return None

	def get_package_id(self,package_id):
		try:
			cur = self.conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
			cur.execute("SELECT id,version,name FROM package WHERE id=%s",(package_id,))
			res = cur.fetchall()
			self.conn.commit()
			package = Package(res[0]['id'],res[0]['version'],res[0]['name'])
			cur.close()
			return package
		except psycopg2.Error as e:
			self.conn.rollback()
			raise Exception("Error retrieving package with id:" + str(package_id) + ". Database error code: "  + str(e.pgcode) + " - Details: " + str(e.pgerror))
			return None


	def get_package_byvalues(self,name,version):
		try:
			cur = self.conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
			cur.execute("SELECT id,name,version FROM package WHERE name=%s AND version=%s",(name,version))
			res = cur.fetchall()
			self.conn.commit()

			packages = []
			for i in res:
				packages.append(Package(i['id'],i['version'],i['name']))
			cur.close()
			return packages
		except psycopg2.Error as e:
			self.conn.rollback()
			raise Exception("Error retrieving package by values:" + name + version + ". Database error code: "  + str(e.pgcode) + " - Details: " + str(e.pgerror))
			return None

	def put_package(self,version,name):
		try:
			cur = self.conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
			cur.execute("INSERT into package(version,name) VALUES (%s, %s)  RETURNING id",(remove_nasties(version),remove_nasties(name)))
			res = cur.fetchall()
			self.conn.commit()
			package = Package(res[0]['id'],version,name)
			cur.close()
			return package
		except psycopg2.Error as e:
			self.conn.rollback()
			raise Exception("Error adding package:" + name + version + ". Database error code: "  + str(e.pgcode) + " - Details: " + str(e.pgerror))
			return None

	def delete_package(self,package_id):
		try:
			cur = self.conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
			cur.execute("DELETE FROM package WHERE id=%s  RETURNING id",(package_id,))
			res = cur.fetchall()
			self.conn.commit()

			if res[0]['id'] == package_id:
				cur.close()
				return True
			else:
				cur.close()
				return False
		except psycopg2.Error as e:
			self.conn.rollback()
			self.log.debug("Error deleting package with id: %s. Database error code: %s - Details: %s.",str(package_id),str(e.pgcode),str(e.pgerror))
			return e.pgcode

	#<<<<<<<<< Packageinstance related Queries >>>>>>>

	def get_packageinstance_id(self,packageinstance_id):
		try:
			cur = self.conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
			cur.execute("SELECT id,package_id,buildenv_id,arch_id,suite_id,dist_id,format_id,master FROM packageinstance  WHERE id=%s",(packageinstance_id,))
			res = cur.fetchall()
			self.conn.commit()

			package = self.get_package_id(res[0]['package_id'])
			build_env = self.get_build_env_id(res[0]['buildenv_id'])
			arch = self.get_arch_id(res[0]['arch_id'])
			suite = self.get_suite_id(res[0]['suite_id'])
			dist = self.get_dist_id(res[0]['dist_id'])
			pkg_format = self.get_format_id(res[0]['format_id'])
			p_i = PackageInstance(res[0]['id'],package,arch,build_env,suite,dist,pkg_format,res[0]['master'])
			cur.close()
			return p_i
		except psycopg2.Error as e:
			self.conn.rollback()
			raise Exception("Error retrieving package instance with:" + str(packageinstance_id) + ". Database error code: "  + str(e.pgcode) + " - Details: " + str(e.pgerror))
			return None

	def count_packageinstances(self):
		try:
			cur = self.conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
			cur.execute("SELECT COUNT(*) FROM packageinstance AS num_packageinstances")
			res = cur.fetchall()
			self.conn.commit()

			cur.close()

			if res[0][0]:
				pages = res[0][0] / self.limit_high;
			pages = 1

			return math.ceil(pages);
		except psycopg2.Error as e:
			self.conn.rollback()
			raise Exception("Error retrieving packageinstances count. Database error code: "  + str(e.pgcode) + " - Details: " + str(e.pgerror))
			return None

	def get_packageinstances(self,page=None):
		try:
			cur = self.conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
			if page:
				# CONSTANT
				offset = (page -1) * self.limit_high;
				cur.execute("SELECT id,package_id,buildenv_id,arch_id,suite_id,dist_id,format_id,master FROM packageinstance ORDER BY id LIMIT %s OFFSET %s", (self.limit_high,offset,))
			else:
				cur.execute("SELECT id,package_id,buildenv_id,arch_id,suite_id,dist_id,format_id,master FROM packageinstance ORDER BY id")
			res = cur.fetchall()
			self.conn.commit()

			packageinstances = []
			for i in res:
				packageinstances.append(self.get_packageinstance_id(i['id']))
			cur.close()
			return packageinstances
		except psycopg2.Error as e:
			self.conn.rollback()
			raise Exception("Error retrieving package instances list. Database error code: "  + str(e.pgcode) + " - Details: " + str(e.pgerror))
			return None

	def get_packageinstances_byname(self, name):
		try:
			cur = self.conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
			cur.execute("SELECT packageinstance.id AS id,package.id AS package_id,buildenv_id,arch_id,suite_id,dist_id,format_id,master FROM packageinstance,package WHERE packageinstance.package_id = package.id AND name = %s ORDER BY package_id, id",(name,))
			res = cur.fetchall()
			self.conn.commit()

			packageinstances = []
			for i in res:
				packageinstances.append(self.get_packageinstance_id(i['id']))
			cur.close()
			return packageinstances
		except psycopg2.Error as e:
			self.conn.rollback()
			raise Exception("Error retrieving package instances by name. Database error code: "  + str(e.pgcode) + " - Details: " + str(e.pgerror))
			return None


	def get_packageinstance_byvalues(self,package,build_env,arch,suite,dist,pkg_format):
		try:
			cur = self.conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
			if build_env:
				cur.execute("SELECT id,package_id,buildenv_id,arch_id,suite_id,dist_id,format_id,master FROM packageinstance WHERE package_id=%s AND buildenv_id=%s AND arch_id=%s AND suite_id=%s AND dist_id=%s AND format_id=%s",(package.id,build_env.id,arch.id,suite.id,dist.id,pkg_format.id))
			else:
				cur.execute("SELECT id,package_id,buildenv_id,arch_id,suite_id,dist_id,format_id,master FROM packageinstance WHERE package_id=%s AND buildenv_id IS NULL AND arch_id=%s AND suite_id=%s AND dist_id=%s AND format_id=%s",(package.id,arch.id,suite.id,dist.id,pkg_format.id))
			res = cur.fetchall()
			self.conn.commit()

			packageinstances = []
			for i in res:
				packageinstances.append(self.get_packageinstance_id(i['id']))
			cur.close()
			return packageinstances
		except psycopg2.Error as e:
			self.conn.rollback()
			raise Exception("Error retrieving package instance by value. Database error code: "  + str(e.pgcode) + " - Details: " + str(e.pgerror))
			return None

	def put_packageinstance(self,package,build_env,arch,suite,dist,pkg_format,master):
		try:

			# The buildenv_id field in the DB is allowed to be null.
			# We may be passed a None build_env object and must handle this.
			if build_env:
				build_env_id = build_env.id
			else:
				build_env_id = None;

			cur = self.conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
			cur.execute("INSERT into packageinstance(package_id,buildenv_id,arch_id,suite_id,dist_id,format_id,master) VALUES (%s, %s, %s, %s, %s, %s, %s)  RETURNING id",(remove_nasties(package.id),remove_nasties(build_env_id),remove_nasties(arch.id),remove_nasties(suite.id),remove_nasties(dist.id),remove_nasties(pkg_format.id),remove_nasties(master)))
			self.conn.commit()
			res = cur.fetchall()
			self.conn.commit()
			p_i = PackageInstance(res[0]['id'],package,arch,build_env,suite,dist,pkg_format,master)
			cur.close()
			return p_i
		except psycopg2.Error as e:
			self.conn.rollback()
			raise Exception("Error adding package instance:" + str(package.id) + ". Database error code: "  + str(e.pgcode) + " - Details: " + str(e.pgerror))
			return None

	def update_packageinstance_masterflag(self,packageinstance_id,master):
		try:
			if master == 1:
				master = True
			elif master == 0:
				master = False
			else:
				return None;

			cur = self.conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
			cur.execute("UPDATE packageinstance SET master=%s WHERE id=%s",(remove_nasties(master),remove_nasties(packageinstance_id)))
			self.conn.commit()
			self.conn.commit()
			cur.close()
			return
		except psycopg2.Error as e:
			self.conn.rollback()
			raise Exception("Error updating package instance master flag:" + str(packageinstance_id) + " to " + str(master) + ". Database error code: "  + str(e.pgcode) + " - Details: " + str(e.pgerror))
			return None

	def delete_packageinstance(self,packageinstance_id):
		try:
			cur = self.conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
			cur.execute("DELETE FROM packageinstance WHERE id=%s RETURNING id",(packageinstance_id,))
			res = cur.fetchall()
			self.conn.commit()

			if res[0]['id'] == packageinstance_id:
				cur.close()
				return True
			else:
				cur.close()
				return False
		except psycopg2.Error as e:
			self.conn.rollback()
			self.log.debug("Error deleting package instance with id: %s. Database error code: %s - Details: %s.",str(packageinstance_id),str(e.pgcode),str(e.pgerror))
			return e.pgcode

	def check_specific_packageinstance_exists(self,build_env,arch,package,distribution,pkg_format,suite):
		try:
			if arch and distribution and pkg_format and package and suite:
				cur = self.conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
				if build_env:
					cur.execute("SELECT id FROM packageinstance WHERE buildenv_id=%s AND arch_id=%s AND dist_id=%s AND format_id=%s AND package_id=%s AND suite_id=%s",(build_env.id,arch.id,distribution.id,pkg_format.id,package.id,suite.id))
				else:
					cur.execute("SELECT id FROM packageinstance WHERE buildenv_id IS NULL AND arch_id=%s AND dist_id=%s AND format_id=%s AND package_id=%s AND suite_id=%s",(arch.id,distribution.id,pkg_format.id,package.id,suite.id))
				res = cur.fetchall()
				self.conn.commit()

				if len(res) > 0:
					#Found specific package instance
					cur.close()
					return True
				else:
					# doesnt exist
					#Cannot find specific package instance
					cur.close()
					return False
			else:
				#Error finding specific package instance
				cur.close()
				return False
		except psycopg2.Error as e:
			self.conn.rollback()
			raise Exception("Error checking package instance exists. Database error code: "  + str(e.pgcode) + " - Details: " + str(e.pgerror))
			return None
	#<<<<<<<<< Report Queries >>>>>>>

	def check_package_has_unfinished_jobs(self, package_id):
		try:
			cur = self.conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
			cur.execute("WITH latest_status AS (SELECT DISTINCT ON (job_id) job_id, status.name FROM jobstatus LEFT JOIN status ON status_id=status.id ORDER BY job_id, time DESC) SELECT job_id, name, package_id FROM latest_status LEFT JOIN job ON latest_status.job_id=job.id LEFT JOIN packageinstance ON packageinstance_id=packageinstance.id WHERE package_id=%s AND name NOT IN ('Done', 'Uploaded', 'Cancelled')",(package_id,));
			res = cur.fetchall()
			self.conn.commit()

			if res and len(res) > 0:
				return True
			else:
				return False
		except psycopg2.Error as e:
			self.conn.rollback()
			raise Exception("Error check package has unfinished jobs. Database error code: "  + str(e.pgcode) + " - Details: " + str(e.pgerror))
			return None

	def get_report_package_instance(self):
		try:
			cur = self.conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
			cur.execute("SELECT packageinstance.id, suite.name AS suite, package.name AS package, package.version AS version, arch.name AS arch, packageinstance.buildenv_id AS buildenv_id, format.name AS format, distribution.name AS dist, packageinstance.master AS master FROM packageinstance LEFT JOIN arch ON arch.id=arch_id LEFT JOIN suite ON suite.id=suite_id LEFT JOIN distribution ON distribution.id=dist_id LEFT JOIN package ON package_id=package.id LEFT JOIN format ON format_id=format.id")
			res = cur.fetchall()
			self.conn.commit()

			package_instances = []
			for i in res :
				package_instances.append(PackageInstance(i['id'], i['package'], i['arch'], i['buildenv_id'], i['suite'], i['dist'], i['format'], i['master']))
			cur.close()
			return package_instances
		except psycopg2.Error as e:
			self.conn.rollback()
			raise Exception("Error retrieving package instance list. Database error code: "  + str(e.pgcode) + " - Details: " + str(e.pgerror))
			return None

	def get_supported_architectures(self,suite) :
		try:
			if suite :
				cur = self.conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
				cur.execute("SELECT arch.id, arch.name, suitearches.master_weight FROM suite LEFT JOIN suitearches ON suite.id=suite_id LEFT JOIN arch ON arch_id = arch.id WHERE suite.name=%s ORDER BY master_weight DESC, random()",[suite])
				res = cur.fetchall()
				self.conn.commit()

				arch_list = []
				for i in res :
					arch_list.append(i['name'])
				cur.close()
				return arch_list
			else:
				cur.close()
				return False
		except psycopg2.Error as e:
			self.conn.rollback()
			raise Exception("Error retrieving supported architectures for:" + suite + ". Database error code: "  + str(e.pgcode) + " - Details: " + str(e.pgerror))
			return None

	def get_supported_build_environments(self,suite) :
		try:
			if suite :
				cur = self.conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
				cur.execute("SELECT DISTINCT ON (buildenv.id) buildenv.id AS buildenv_id FROM suitearches LEFT JOIN buildenvsuitearch ON suitearches.id=suitearch_id LEFT JOIN buildenv ON buildenvsuitearch.buildenv_id=buildenv.id WHERE suitearches.suite_id=(SELECT id FROM suite WHERE name=%s)",(remove_nasties(suite),))
				res = cur.fetchall()
				self.conn.commit()
				env_list = []
				for i in res :
					build_env = self.get_build_env_id(i['buildenv_id'])
					#self.log.debug("SUITE (%s) HAS SUPPORTED BUILD ENV:%s",suite,build_env.name)
					env_list.append(build_env)
				cur.close()
				return env_list
			else:
				cur.close()
				return False
		except psycopg2.Error as e:
			self.conn.rollback()
			raise Exception("Error retrieving supported build environments for:" + suite + ". Database error code: "  + str(e.pgcode) + " - Details: " + str(e.pgerror))
			return None

	def get_supported_build_env_suite_arches(self,suite) :
		try:
			if suite :
				cur = self.conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
				cur.execute("SELECT buildenv.id AS buildenv_id, suitearches.id AS suitearch_id, suitearches.master_weight AS suitearch_master_weight, buildenvsuitearch.id AS buildenvsuitearch_id FROM suitearches LEFT JOIN buildenvsuitearch ON suitearches.id=suitearch_id LEFT JOIN buildenv ON buildenvsuitearch.buildenv_id=buildenv.id WHERE suitearches.suite_id=(SELECT id FROM suite WHERE name=%s) ORDER BY buildenv_id, suitearch_master_weight DESC",(remove_nasties(suite),))
				res = cur.fetchall()
				self.conn.commit()
				build_env_suite_arch_list = []
				for i in res :
					suitearch = self.get_suitearch_id(i['suitearch_id'])
					build_env = self.get_build_env_id(i['buildenv_id'])
					if not build_env :
						buildenvsuitearch = BuildEnvSuiteArch(i['buildenvsuitearch_id'],None,suitearch)
					else :
						buildenvsuitearch = BuildEnvSuiteArch(i['buildenvsuitearch_id'],build_env,suitearch)
					build_env_suite_arch_list.append(buildenvsuitearch)
				cur.close()
				return build_env_suite_arch_list
			else:
				cur.close()
				return False
		except psycopg2.Error as e:
			self.conn.rollback()
			raise Exception("Error retrieving supported build environments for:" + suite + ". Database error code: "  + str(e.pgcode) + " - Details: " + str(e.pgerror))
			return None


	# Note: True = failed, false = Ok. Should probably be renamed isInBlacklist() or similar.
	def check_blacklist(self,field,value):
		try:
			cur = self.conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
			cur.execute("SELECT id,field,regex FROM blacklist WHERE field=%s",[field])
			res = cur.fetchall()
			self.conn.commit()

			for i in res:
				# Check passed in value using i.regex - Search() or Match() ?
				match = re.search(i['regex'], value) # An invalid regexp will throw an exception here. Valid regexp is i.e: name field and (.*-dev) or vcs_uri field and (.*/users/*)
				if match is not None:
					self.log.debug("BLACKLISTED! %s matches %s : %s", str(i['regex']), str(field), str(value))
					cur.close()
					return True
				else:
					cur.close()
					return False
			cur.close()
			return False # If no results, that is fine too.
		except psycopg2.Error as e:
			self.conn.rollback()
			raise Exception("Error checking blacklist. Database error code: "  + str(e.pgcode) + " - Details: " + str(e.pgerror))
			return None

	def count_blacklist(self):
		try:
			cur = self.conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
			cur.execute("SELECT COUNT(*) FROM blacklist AS num_blacklist")
			res = cur.fetchall()
			self.conn.commit()

			cur.close()

			if res[0][0]:
				pages = res[0][0] / self.limit_low;
			else:
				pages = 1

			return math.ceil(pages);
		except psycopg2.Error as e:
			self.conn.rollback()
			raise Exception("Error retrieving blacklist count. Database error code: "  + str(e.pgcode) + " - Details: " + str(e.pgerror))
			return None

	def get_blacklist(self,page=None):
		try:
			cur = self.conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
			if page:

				offset = (page -1) * self.limit_low;
				cur.execute("SELECT id,field,regex FROM blacklist ORDER BY field LIMIT %s OFFSET %s", (self.limit_low,offset,))
			else:
				cur.execute("SELECT id,field,regex FROM blacklist ORDER BY field")
			res = cur.fetchall()
			self.conn.commit()

			blacklist = []
			for i in res:
				blacklist.append(Blacklist(i['id'],i['field'],i['regex']))
			cur.close()
			return blacklist
		except psycopg2.Error as e:
			self.conn.rollback()
			raise Exception("Error retrieving blacklist. Database error code: "  + str(e.pgcode) + " - Details: " + str(e.pgerror))
			return None

	def get_blacklist_id(self,blacklist_id):
		try:
			cur = self.conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
			cur.execute("SELECT id,field,regex FROM blacklist WHERE id=%s",(blacklist_id,))
			res = cur.fetchall()
			self.conn.commit()
			blacklist = Blacklist(res[0]['id'],res[0]['field'],res['0']['regex'])
			cur.close()
			return blacklist
		except psycopg2.Error as e:
			self.conn.rollback()
			raise Exception("Error retrieving blacklist rule with id:" + str(blacklist_id) + ". Database error code: "  + str(e.pgcode) + " - Details: " + str(e.pgerror))
			return None

	def put_blacklist(self,field,regex):
		try:
			cur = self.conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
			cur.execute("INSERT into blacklist(field,regex) VALUES (%s,%s)  RETURNING id",(remove_nasties(field),remove_nasties(regex)))
			res = cur.fetchall()
			self.conn.commit()
			blacklist = Blacklist(res[0]['id'],field,regex)
			cur.close()
			return blacklist
		except psycopg2.Error as e:
			self.conn.rollback()
			raise Exception("Error adding blacklist rule:" + " .Database error code: "  + str(e.pgcode) + " - Details: " + str(e.pgerror))
			return None

	def delete_blacklist(self,blacklist_id):
		try:
			cur = self.conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
			cur.execute("DELETE FROM blacklist WHERE id=%s RETURNING id",(blacklist_id,))
			res = cur.fetchall()
			self.conn.commit()

			if res[0]['id'] == blacklist_id:
				cur.close()
				return True
			else:
				cur.close()
				return False
		except psycopg2.Error as e:
			self.conn.rollback()
			self.log.debug("Error deleting blacklist with id: %s. Database error code: %s - Details: %s.",str(blacklist_id),str(e.pgcode),str(e.pgerror))
			return e.pgcode
