#!/usr/bin/python2.7
# encoding: utf-8
'''
Tool to control things on onapp-based cloud hosting
'''

import sys
import os
import json
import urllib2
import dateutil.parser
import time
import ConfigParser
from tabulate import tabulate
from argparse import ArgumentParser
from argparse import RawDescriptionHelpFormatter
from datetime import datetime

__all__ = []
__version__ = 0.1
__date__ = '2015-02-16'
__updated__ = '2015-02-16'

DEBUG = True

class Error(Exception):
    '''Generic exception to raise and log different fatal errors.'''
    def __init__(self, msg):
        super(Error).__init__(type(self))
        self.msg = msg
    def __str__(self):
        return self.msg
    def __unicode__(self):
        return self.msg
    
class Config:
    def __init__(self):
        # Load config
        self.config = ConfigParser.ConfigParser(allow_no_value=True)
        try:
            self.config.readfp(open('config.ini'))
        except:
            self.config = None
    
    def get(self, section, option):
        if not self.config: return None;
        if not self.config.has_section(section): return None;
        if not self.config.has_option(section, option): return None;
        return self.config.get(section, option);
    
    def general(self, option):
        return self.get("general", option);

def installBasicAuth(baseUrl, user, passwd):
    password_mgr = urllib2.HTTPPasswordMgrWithDefaultRealm()
    password_mgr.add_password(None, baseUrl, user, passwd)
    handler = urllib2.HTTPBasicAuthHandler(password_mgr)
    opener = urllib2.build_opener(handler) # Install the opener.
    # Now all calls to urllib2.urlopen use our opener.
    urllib2.install_opener(opener)

def getJson(url):
    request = urllib2.Request(url)
    response = urllib2.urlopen(request)
    body = response.read()
    dom = json.loads(body)
    return dom

def postJson(url, requestDom):
    requestBody = json.dumps(requestDom)
    request = urllib2.Request(url, requestBody, {'Content-Type': 'application/json'})
    response = urllib2.urlopen(request)
    responseBody = response.read()
    responseDom = json.loads(responseBody)
    return responseDom

def listVMs(args):
    vms = getVMs(args)
    vmInfos = [getVMInfo(vm) for vm in vms]
    print tabulate(vmInfos, headers=["Hostname", "ID", "RAM", "Booted", "Note"])

def listBackups(args):
    vms = getVMs(args)
    
    if not args.vmHostnames: # List backups for all vms if no hosts are specified
        args.vmHostnames = [vm["hostname"] for vm in vms]
    
    totalSize = 0
    for vmHostname in args.vmHostnames:
        vmID = getVMID(vms, vmHostname)
        backups = getVMBackups(args.url, vmID, lambda backup: True)
        totalSize += sum(backup["backup_size"] for backup in backups)
        backupInfos = [getBackupInfo(backup) for backup in backups]
        print "\nBackups for {}:\n".format(vmHostname)
        print tabulate(backupInfos, headers=["Created at", "Built", "Built at", "Size", "Note"])
    
    print "\nTotal space taken by above backups: {} MB".format(totalSize / 1024)

def doBackup(args):
    vms = getVMs(args)
    isBuiltTests = []
    if not args.note: args.note = "onapptool backup"
    note = args.note + " " + dateToString(datetime.now())
    
    printWithTime("Starting backups on {} VMs".format(len(args.vmHostnames)))
    
    # Start primary disk backup for every host
    for vmHostname in args.vmHostnames:
        vmID = getVMID(vms, vmHostname)
        diskID = getVMPrimaryDiskID(args.url, vmID)
        request = { "backup": {
            "note": note
        }}
        creationUrl = "{0}/settings/disks/{1}/backups.json".format(args.url, diskID)
        response = postJson(creationUrl, request)
        backup = response["backup"]
        backupID = backup["id"]
        
        test = lambda a=args.url, b=vmID, c=vmHostname, d=backupID: isBackupBuilt(a,b,c,d)
        isBuiltTests.append(test)
        
    # Poll for backup completion until all backups are ready
    while isBuiltTests:
        isBuiltTests = [test for test in isBuiltTests if not test()]
        if not isBuiltTests: break
        printWithTime("{} backups still building".format(len(isBuiltTests)))
        time.sleep(60)
        
    printWithTime("Backups on all VMs finished successfully!")
    

def isBackupBuilt(baseUrl, vmID, vmHostname, backupID):
    backups = getVMBackups(baseUrl, vmID, lambda backup: backup["id"] == backupID)
    assert len(backups) == 1
    backup = backups[0]
    built = backup["built"]
    if built:
        printWithTime("Backup (id={}) on {} finished!".format(backupID, vmHostname))
    return built
    
def getVMInfo(vm):
    return [vm["hostname"], vm["id"], vm["memory"], str(vm["booted"]), vm["note"]]

def getVMID(vms, vmHostname):
    try:
        return next(vm["id"] for vm in vms if vm["hostname"] == vmHostname)
    except StopIteration:
        raise ValueError("No vm with hostname {} found".format(vmHostname))

def getVMs(args):
    url = "{0}/virtual_machines.json".format(args.url)
    dom = getJson(url)
    return [item["virtual_machine"] for item in dom]

def getVMBackups(baseUrl, vmId, backupFilter):
    url = "{0}/virtual_machines/{1}/backups.json".format(baseUrl, vmId)
    dom = getJson(url)
    return [item["backup"] for item in dom if backupFilter(item["backup"])]

def getVMDisks(baseUrl, vmId):
    url = "{0}/virtual_machines/{1}/disks.json".format(baseUrl, vmId)
    dom = getJson(url)
    return [item["disk"] for item in dom]

def getVMPrimaryDiskID(baseUrl, vmId):
    disks = getVMDisks(baseUrl, vmId)
    try:
        return next(disk["id"] for disk in disks if disk["primary"])
    except StopIteration:
        raise ValueError("No primary disk found for VM ID {}".format(vmId))

def getBackupInfo(backup):
    return [utcDateToLocal(backup["created_at"]), str(backup["built"]), 
            utcDateToLocal(backup["built_at"]), backup["backup_size"] / 1024, backup["note"]]

def utcDateToLocal(utcDate):
    if utcDate == None: return "None"
    date = dateutil.parser.parse(utcDate)
    return dateToString(date)

def dateToString(date):
    return date.strftime("%x %H:%M")

def printWithTime(msg):
    time = datetime.now().strftime("%H:%M")
    print "["+ time + "] " + msg

def main(argv=None): # IGNORE:C0111
    '''Command line options.'''

    if argv is None:
        argv = sys.argv
    else:
        sys.argv.extend(argv)

    program_name = os.path.basename(sys.argv[0])
    program_shortdesc = __import__('__main__').__doc__.split("\n")[1]

    try:
        # Load config
        config = Config()
        
        # Setup argument parser
        parser = ArgumentParser(description=program_shortdesc, formatter_class=RawDescriptionHelpFormatter)
        parser.add_argument("-t", dest="url", help="URL of the target host", default=config.general("url"))
        parser.add_argument("-u", dest="user", help="user for authentication", default=config.general("user"))
        parser.add_argument("-p", dest="passwd", help="password for authentication", default=config.general("pass"))
        
        actionParsers = parser.add_subparsers(help="what to do")
        
        vmParser = actionParsers.add_parser("vms", help="list available virtual machines")
        vmParser.set_defaults(func=listVMs)
        
        backupsParser = actionParsers.add_parser("backups", help="list backups on all or specified vms")
        backupsParser.add_argument(dest="vmHostnames", nargs="*")
        backupsParser.set_defaults(func=listBackups)
        
        dobackupParser = actionParsers.add_parser("dobackup", help="start backups on specified vms, and poll their completion status every minute")
        dobackupParser.add_argument(dest="vmHostnames", nargs="+")
        dobackupParser.add_argument("-n", dest="note", help="note to be attached to the backups")
        dobackupParser.set_defaults(func=doBackup)

        # Process arguments
        args = parser.parse_args()
        if args.user and args.passwd:
            installBasicAuth(args.url, args.user, args.passwd)
        if not args.url:
            raise Error("URL of the target host is not defined")
        args.func(args)
    
    except KeyboardInterrupt:
        ### handle keyboard interrupt ###
        return 0
    except Exception, e:
        if DEBUG:
            raise
        prefix = "error"
        indent = len(prefix) * " "
        sys.stderr.write(prefix + ": " + str(e) + "\n")
        sys.stderr.write(indent + "  for help use --help\n")
        return 2

def addTargetHostParserArg(parser):
    return parser.add_argument(dest="url", help="URL of the target host")

if __name__ == "__main__":
    sys.exit(main())
