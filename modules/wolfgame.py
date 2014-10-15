# Copyright (c) 2011, Jimmy Cao
# All rights reserved.

# Redistribution and use in source and binary forms, with or without modification, are permitted provided that the following conditions are met:

# Redistributions of source code must retain the above copyright notice, this list of conditions and the following disclaimer.
# Redistributions in binary form must reproduce the above copyright notice, this list of conditions and the following disclaimer in the documentation and/or other materials provided with the distribution.
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.

from oyoyo.parse import parse_nick
import settings.wolfgame as var
import botconfig
from tools.wolfgamelogger import WolfgameLogger
from tools import decorators
from datetime import datetime, timedelta
import threading
import random
import copy
import time
import re
import logging
import sys
import os
import imp
import math
import fnmatch

COMMANDS = {}
PM_COMMANDS = {}
HOOKS = {}

cmd = decorators.generate(COMMANDS)
pmcmd = decorators.generate(PM_COMMANDS)
hook = decorators.generate(HOOKS, raw_nick=True, permissions=False)

# Game Logic Begins:

var.LAST_PING = None  # time of last ping
var.LAST_STATS = None
var.LAST_VOTES = None
var.LAST_ADMINS = None

var.USERS = {}

var.PINGING = False
var.ADMIN_PINGING = False
var.ROLES = {"persoon" : []}
var.ORIGINAL_ROLES = {}
var.PLAYERS = {}
var.DCED_PLAYERS = {}
var.ADMIN_TO_PING = None
var.AFTER_FLASTGAME = None
var.PHASE = "geen"  # "join", "day", or "night"
var.TIMERS = {}
var.DEAD = []

var.ORIGINAL_SETTINGS = {}

var.LAST_SAID_TIME = {}

var.GAME_START_TIME = datetime.now()  # for idle checker only
var.CAN_START_TIME = 0
var.GRAVEYARD_LOCK = threading.RLock()
var.GAME_ID = 0

var.DISCONNECTED = {}  # players who got disconnected

var.LOGGER = WolfgameLogger(var.LOG_FILENAME, var.BARE_LOG_FILENAME)

if botconfig.DEBUG_MODE:
    var.NIGHT_TIME_LIMIT = 0  # 90
    var.NIGHT_TIME_WARN = 0
    var.DAY_TIME_LIMIT_WARN = 0
    var.DAY_TIME_LIMIT_CHANGE = 0
    var.KILL_IDLE_TIME = 0 #300
    var.WARN_IDLE_TIME = 0 #180

        
def connect_callback(cli):
    to_be_devoiced = []
    cmodes = []
    
    @hook("quietlist", hookid=294)
    def on_quietlist(cli, server, botnick, channel, q, quieted, by, something):
        if re.match(".+\!\*@\*", quieted):  # only unquiet people quieted by bot
            cmodes.append(("-q", quieted))

    @hook("whospcrpl", hookid=294)
    def on_whoreply(cli, server, nick, ident, cloak, user, status, acc):
        if user in var.USERS: return  # Don't add someone who is already there
        if user == botconfig.NICK:
            cli.nickname = user
            cli.ident = ident
            cli.hostmask = cloak
        if acc == "0":
            acc = "*"
        if "+" in status:
            to_be_devoiced.append(user)
        var.USERS[user] = dict(cloak=cloak,account=acc)
        
    @hook("endofwho", hookid=294)
    def afterwho(*args):
        for nick in to_be_devoiced:
            cmodes.append(("-v", nick))
        # devoice all on connect
        
        @hook("mode", hookid=294)
        def on_give_me_ops(cli, blah, blahh, modeaction, target="", *other):
            if modeaction == "+o" and target == botconfig.NICK and var.PHASE == "geen":
                
                @hook("quietlistend", 294)
                def on_quietlist_end(cli, svr, nick, chan, *etc):
                    if chan == botconfig.CHANNEL:
                        decorators.unhook(HOOKS, 294)
                        mass_mode(cli, cmodes)
                
                cli.mode(botconfig.CHANNEL, "q")  # unquiet all

                cli.mode(botconfig.CHANNEL, "-m")  # remove -m mode from channel
            elif modeaction == "+o" and target == botconfig.NICK and var.PHASE != "geen":
                decorators.unhook(HOOKS, 294)  # forget about it


    cli.who(botconfig.CHANNEL, "%nuhaf")


def mass_mode(cli, md):
    """ Example: mass_mode(cli, (('+v', 'asdf'), ('-v','wobosd'))) """
    lmd = len(md)  # store how many mode changes to do
    for start_i in range(0, lmd, 4):  # 4 mode-changes at a time
        if start_i + 4 > lmd:  # If this is a remainder (mode-changes < 4)
            z = list(zip(*md[start_i:]))  # zip this remainder
            ei = lmd % 4  # len(z)
        else:
            z = list(zip(*md[start_i:start_i+4])) # zip four
            ei = 4 # len(z)
        # Now z equal something like [('+v', '-v'), ('asdf', 'wobosd')]
        arg1 = "".join(z[0])
        arg2 = " ".join(z[1])  # + " " + " ".join([x+"!*@*" for x in z[1]])
        cli.mode(botconfig.CHANNEL, arg1, arg2)
        
def pm(cli, target, message):  # message either privmsg or notice, depending on user settings
    if target in var.USERS and var.USERS[target]["cloak"] in var.SIMPLE_NOTIFY:
        cli.notice(target, message)
    else:
        cli.msg(target, message)

def reset_settings():
    for attr in list(var.ORIGINAL_SETTINGS.keys()):
        setattr(var, attr, var.ORIGINAL_SETTINGS[attr])
    dict.clear(var.ORIGINAL_SETTINGS)


def reset(cli):
    chan = botconfig.CHANNEL
    var.PHASE = "geen"

    for x, timr in var.TIMERS.items():
        timr.cancel()
    var.TIMERS = {}
    
    var.GAME_ID = 0

    cli.mode(chan, "-m")
    cmodes = []
    for plr in var.list_players():
        cmodes.append(("-v", plr))
    for deadguy in var.DEAD:
       cmodes.append(("-q", deadguy+"!*@*"))
    mass_mode(cli, cmodes)
    var.DEAD = []

    var.ROLES = {"persoon" : []}

    reset_settings()

    dict.clear(var.LAST_SAID_TIME)
    dict.clear(var.PLAYERS)
    dict.clear(var.DCED_PLAYERS)
    dict.clear(var.DISCONNECTED)


@pmcmd("fdie", "fbye", admin_only=True)
@cmd("fdie", "fbye", admin_only=True)
def forced_exit(cli, nick, *rest):  # Admin Only
    """Forces the bot to close"""
    
    if var.PHASE in ("dag", "nacht"):
        stop_game(cli)
    else:
        reset(cli)

    cli.quit("Gestopt door "+nick)



@pmcmd("frestart", admin_only=True)
@cmd("frestart", admin_only=True)
def restart_program(cli, nick, *rest):
    """Restarts the bot."""
    try:
        if var.PHASE in ("dag", "nacht"):
            stop_game(cli)
        else:
            reset(cli)

        cli.quit("Herstart door "+nick)
        raise SystemExit
    finally:
        print("HERSTARTEN")
        python = sys.executable
        if rest[-1].strip().lower() == "debugmode":
            os.execl(python, python, sys.argv[0], "--debug")
        elif rest[-1].strip().lower() == "normalmode":
            os.execl(python, python, sys.argv[0])
        elif rest[-1].strip().lower() == "verbosemode":
            os.execl(python, python, sys.argv[0], "--verbose")
        else:
            os.execl(python, python, *sys.argv)
    
            

@cmd("ping")
def pinger(cli, nick, chan, rest):
    """Pinged het kanaal om de aandacht te krijgen van de gebruikers.  Gebruik gelimiteerd."""
    if (var.LAST_PING and
        var.LAST_PING + timedelta(seconds=var.PING_WAIT) > datetime.now()):
        cli.notice(nick, ("Dit commando heeft een gebruikers limiet. " +
                          "Even wachten dus voor je hem weer gebruikt."))
        return
        
    if var.PHASE in ('nacht','dag'):
        cli.notice(nick, "Je kunt dit commando niet gebruiken zolang het spel bezig is.")
        return

    var.LAST_PING = datetime.now()
    if var.PINGING:
        return
    var.PINGING = True
    TO_PING = []



    @hook("whoreply", hookid=800)
    def on_whoreply(cli, server, dunno, chan, dunno1,
                    cloak, dunno3, user, status, dunno4):
        if not var.PINGING: return
        if user in (botconfig.NICK, nick): return  # Don't ping self.

        if (all((not var.OPT_IN_PING,
                 'G' not in status,  # not /away
                 '+' not in status,  # not already joined (voiced)
                 cloak not in var.AWAY)) or
            all((var.OPT_IN_PING, '+' not in status,
                 cloak in var.PING_IN))):

            TO_PING.append(user)


    @hook("endofwho", hookid=800)
    def do_ping(*args):
        if not var.PINGING: return

        TO_PING.sort(key=lambda x: x.lower())
        
        cli.msg(botconfig.CHANNEL, "PING! "+" ".join(TO_PING))
        var.PINGING = False
 
        minimum = datetime.now() + timedelta(seconds=var.PING_MIN_WAIT)
        if not var.CAN_START_TIME or var.CAN_START_TIME < minimum:
           var.CAN_START_TIME = minimum

        decorators.unhook(HOOKS, 800)

    cli.who(botconfig.CHANNEL)


@cmd("simple", raw_nick = True)
@pmcmd("simple", raw_nick = True)
def mark_simple_notify(cli, nick, *rest):
    """If you want the bot to NOTICE you for every interaction"""
    
    nick, _, __, cloak = parse_nick(nick)
    
    if cloak in var.SIMPLE_NOTIFY:
        var.SIMPLE_NOTIFY.remove(cloak)
        var.remove_simple_rolemsg(cloak)
        
        cli.notice(nick, "Je ontvangt geen korte rol instructies meer.")
        return
        
    var.SIMPLE_NOTIFY.append(cloak)
    var.add_simple_rolemsg(cloak)
    
    cli.notice(nick, "Je ontvangt korte rol instructies.")

if not var.OPT_IN_PING:
    @cmd("away", raw_nick=True)
    @pmcmd("away", raw_nick=True)
    def away(cli, nick, *rest):
        """Use this to activate your away status (so you aren't pinged)."""
        cloak = parse_nick(nick)[3]
        nick = parse_nick(nick)[0]
        if cloak in var.AWAY:
            var.AWAY.remove(cloak)
            var.remove_away(cloak)

            cli.notice(nick, "Je staat niet langer op afwezig.")
            return
        var.AWAY.append(cloak)
        var.add_away(cloak)

        cli.notice(nick, "Je staat gemarkeerd als afwezig.")

    @cmd("back", raw_nick=True)
    @pmcmd("back", raw_nick=True)
    def back_from_away(cli, nick, *rest):
        """Unmarks away status"""
        cloak = parse_nick(nick)[3]
        nick = parse_nick(nick)[0]
        if cloak not in var.AWAY:
            cli.notice(nick, "Je staat niet gemarkeerd als afwezig.")
            return
        var.AWAY.remove(cloak)
        var.remove_away(cloak)

        cli.notice(nick, "Je staat niet langer op afwezig.")


else:  # if OPT_IN_PING setting is on
    @cmd("in", raw_nick=True)
    @pmcmd("in", raw_nick=True)
    def get_in(cli, nick, *rest):
        """Get yourself in the ping list"""
        nick, _, _, cloak = parse_nick(nick)
        if cloak in var.PING_IN:
            cli.notice(nick, "Je staat al aangemeld")
            return
        var.PING_IN.append(cloak)
        var.add_ping(cloak)

        cli.notice(nick, "Je bent nu aangemeld.")

    @cmd("out", raw_nick=True)
    @pmcmd("out", raw_nick=True)
    def get_out(cli, nick, *rest):
        """Removes yourself from the ping list"""
        nick, _, _, cloak = parse_nick(nick)
        if cloak in var.PING_IN:
            var.PING_IN.remove(cloak)
            var.remove_ping(cloak)

            cli.notice(nick, "Je bent niet meer aangemeld.")
            return
        cli.notice(nick, "Je bent niet aangemeld.")


@cmd("fping", admin_only=True)
def fpinger(cli, nick, chan, rest):
    var.LAST_PING = None
    pinger(cli, nick, chan, rest)



@cmd("join", raw_nick=True)
def join(cli, nick, chann_, rest):
    """Either starts a new game of Werewolf or joins an existing game that has not started yet."""
    pl = var.list_players()
    
    chan = botconfig.CHANNEL
    
    nick, _, __, cloak = parse_nick(nick)
    
    if var.PHASE == "geen":
    
        cli.mode(chan, "+v", nick)
        var.ROLES["persoon"].append(nick)
        var.PHASE = "join"
        var.WAITED = 0
        var.GAME_ID = time.time()
        var.CAN_START_TIME = datetime.now() + timedelta(seconds=var.MINIMUM_WAIT)
        cli.msg(chan, ('\u0002{0}\u0002 heeft Weerwolven van Wakkerdam gestart. '+
                      'Tik "{1}join" voor deelname. Tik "{1}start" Om het spel te starten. '+
                      'Tik "{1}wacht" om de tijd voor deelname te verlengen.').format(nick, botconfig.CMD_CHAR))
    elif nick in pl:
        cli.notice(nick, "Je speelt al mee!")
    elif len(pl) >= var.MAX_PLAYERS:
        cli.notice(nick, "Maximaal aantal spelers bereikt!  Probeer het later nog eens.")
    elif var.PHASE != "join":
        cli.notice(nick, "Sorry het spel is al bezig.  Probeer het later nog eens.")
    else:
    
        cli.mode(chan, "+v", nick)
        var.ROLES["persoon"].append(nick)
        cli.msg(chan, '\u0002{0}\u0002 doet mee met het spel.'.format(nick))
        
        var.LAST_STATS = None # reset


@cmd("fjoin", admin_only=True)
def fjoin(cli, nick, chann_, rest):
    noticed = False
    chan = botconfig.CHANNEL
    if not rest.strip():
        join(cli, nick, chan, "")

    for a in re.split(" +",rest):
        a = a.strip()
        if not a:
            continue
        ul = list(var.USERS.keys())
        ull = [u.lower() for u in ul]
        if a.lower() not in ull:
            if not is_fake_nick(a) or not botconfig.DEBUG_MODE:
                if not noticed:  # important
                    cli.msg(chan, nick+(": Je kunt alleen fjoin gebruiken "+
                                        "personen zijn in dit kanaal."))
                    noticed = True
                continue
        if not is_fake_nick(a):
            a = ul[ull.index(a.lower())]
        if a != botconfig.NICK:
            join(cli, a.strip(), chan, "")
        else:
            cli.notice(nick, "Nee, Dat is niet toegestaan.")

@cmd("fleave","fquit","fdel", admin_only=True)
def fleave(cli, nick, chann_, rest):
    chan = botconfig.CHANNEL
    
    if var.PHASE == "geen":
        cli.notice(nick, "Er is geen spel bezig.")
    for a in re.split(" +",rest):
        a = a.strip()
        if not a:
            continue
        pl = var.list_players()
        pll = [x.lower() for x in pl]
        if a.lower() in pll:
            a = pl[pll.index(a.lower())]
        else:
            cli.msg(chan, nick+": Deze persoon speelt niet mee.")
            return
        cli.msg(chan, ("\u0002{0}\u0002 dwingt "+
                       " \u0002{1}\u0002 het spel te verlaten.").format(nick, a))
        cli.msg(chan, "Hij/zij was een \02{0}\02.".format(var.get_role(a)))
        if var.PHASE in ("dag", "nacht"):
            var.LOGGER.logMessage("{0} dwingt {1} om het spel te verlaten.".format(nick, a))
            var.LOGGER.logMessage("Hij/zij was een {0}.".format(var.get_role(a)))
        del_player(cli, a)


@cmd("fstart", admin_only=True)
def fstart(cli, nick, chan, rest):
    var.CAN_START_TIME = datetime.now()
    cli.msg(botconfig.CHANNEL, "\u0002{0}\u0002 heeft het spel gestart.".format(nick))
    start(cli, chan, chan, rest)



@hook("kick")
def on_kicked(cli, nick, chan, victim, reason):
    if victim == botconfig.NICK:
        cli.join(botconfig.CHANNEL)
        cli.msg("ChanServ", "op "+botconfig.CHANNEL)


@hook("account")
def on_account(cli, nick, acc):
    nick = parse_nick(nick)[0]    
    if nick in var.USERS.keys():
        var.USERS[nick]["account"] = acc

@cmd("stats")
def stats(cli, nick, chan, rest):
    """Display the player statistics"""
    if var.PHASE == "geen":
        cli.notice(nick, "Er is nu geen spel bezig.")
        return
        
    pl = var.list_players()
    
    if nick in pl or var.PHASE == "join":
        # only do this rate-limiting stuff if the person is in game
        if (var.LAST_STATS and
            var.LAST_STATS + timedelta(seconds=var.STATS_RATE_LIMIT) > datetime.now()):
            cli.msg(chan, nick+": Dit commando heeft een gebruikslimiet.")
            return
            
        var.LAST_STATS = datetime.now()
    
    pl.sort(key=lambda x: x.lower())
    if len(pl) > 1:
        msg = '{0}: \u0002{1}\u0002 spelers: {2}'.format(nick,
            len(pl), ", ".join(pl))
    else:
        msg = '{0}: \u00021\u0002 speler: {1}'.format(nick, pl[0])
    
    if nick in pl or var.PHASE == "join":
        cli.msg(chan, msg)
        var.LOGGER.logMessage(msg.replace("\02", ""))
    else:
        cli.notice(nick, msg)
        
    if var.PHASE == "join":
        return

    message = []
    f = False  # set to true after the is/are verb is decided
    l1 = [k for k in var.ROLES.keys()
          if var.ROLES[k]]
    l2 = [k for k in var.ORIGINAL_ROLES.keys()
          if var.ORIGINAL_ROLES[k]]
    rs = list(set(l1+l2))
        
    # Due to popular demand, picky ordering
    if "wolf" in rs:
        rs.remove("wolf")
        rs.insert(0, "wolf")
    if "ziener" in rs:
        rs.remove("ziener")
        rs.insert(1, "ziener")
    if "burger" in rs:
        rs.remove("burger")
        rs.append("burger")
        
        
    firstcount = len(var.ROLES[rs[0]])
    if firstcount > 1 or not firstcount:
        vb = "zijn"
    else:
        vb = "is"
    for role in rs:
        count = len(var.ROLES[role])
        if count > 1 or count == 0:
            message.append("\u0002{0}\u0002 {1}".format(count if count else "\u0002nee\u0002", var.plural(role)))
        else:
            message.append("\u0002{0}\u0002 {1}".format(count, role))
    stats_mssg =  "{0}: Daar {3} {1}, en {2}.".format(nick,
                                                        ", ".join(message[0:-1]),
                                                        message[-1],
                                                        vb)
    if nick in pl or var.PHASE == "join":
        cli.msg(chan, stats_mssg)
        var.LOGGER.logMessage(stats_mssg.replace("\02", ""))
    else:
        cli.notice(nick, stats_mssg)



def hurry_up(cli, gameid, change):
    if var.PHASE != "dag": return
    if gameid:
        if gameid != var.DAY_ID:
            return

    chan = botconfig.CHANNEL
    
    if not change:
        cli.msg(chan, ("\02Als de zon gestaag naar de horizon zakt, de schaduwen van de " +
                      "eikenbomen langer worden, worden de burgers er aan herinnerd dat er weinig " +
                      "tijd over is om tot een besluit te komen; Als de duisternis valt voor de beslissing " +
                      "is gevallen, de meerderheid van stemmen zal dan winnen. Er zal niemand worden " +
                      "geëlimineerd als er geen of een gelijk aantal stemmen zijn.\02"))
        if not var.DAY_TIME_LIMIT_CHANGE:
            return
        tmr = threading.Timer(var.DAY_TIME_LIMIT_CHANGE, hurry_up, [cli, var.DAY_ID, True])
        tmr.daemon = True
        var.TIMERS["dag"] = tmr
        tmr.start()
        return
        
    
    var.DAY_ID = 0
    
    pl = var.list_players()
    avail = len(pl) - len(var.WOUNDED)
    votesneeded = avail // 2 + 1

    found_dup = False
    maxfound = (0, "")
    for votee, voters in iter(var.VOTES.items()):
        if len(voters) > maxfound[0]:
            maxfound = (len(voters), votee)
            found_dup = False
        elif len(voters) == maxfound[0]:
            found_dup = True
    if maxfound[0] > 0 and not found_dup:
        cli.msg(chan, "De zon gaat onder.")
        var.LOGGER.logMessage("De zon gaat onder.")
        var.VOTES[maxfound[1]] = [None] * votesneeded
        chk_decision(cli)  # Induce a lynch
    else:
        cli.msg(chan, ("Zodra de zon ondergaat, zijn de burger het er over eens om "+
                      "naar bed te gaan en te wachten op de morgen."))
        var.LOGGER.logMessage(("Zodra de zon ondergaat, zijn de burger het er over eens om "+
                               "naar bed te gaan en te wachten op de morgen."))
        transition_night(cli)
        



@cmd("fnight", admin_only=True)
def fnight(cli, nick, chan, rest):
    if var.PHASE != "dag":
        cli.notice(nick, "Het is niet overdag.")
    else:
        hurry_up(cli, 0, True)


@cmd("fday", admin_only=True)
def fday(cli, nick, chan, rest):
    if var.PHASE != "nacht":
        cli.notice(nick, "Het is geen nacht.")
    else:
        transition_day(cli)



def chk_decision(cli):
    chan = botconfig.CHANNEL
    pl = var.list_players()
    avail = len(pl) - len(var.WOUNDED)
    votesneeded = avail // 2 + 1
    for votee, voters in iter(var.VOTES.items()):
        if len(voters) >= votesneeded:
            lmsg = random.choice(var.LYNCH_MESSAGES).format(votee, var.get_role(votee))
            cli.msg(botconfig.CHANNEL, lmsg)
            var.LOGGER.logMessage(lmsg.replace("\02", ""))
            var.LOGGER.logBare(votee, "LYNCHED")
            if del_player(cli, votee, True):
                transition_night(cli)



@cmd("votes")
def show_votes(cli, nick, chan, rest):
    """Displays the voting statistics."""
    
    if var.PHASE in ("geen", "join"):
        cli.notice(nick, "Er draait momenteel geen spel.")
        return
    if var.PHASE != "dag":
        cli.notice(nick, "Stemmen kan alleen overdag.")
        return
    
    if (var.LAST_VOTES and
        var.LAST_VOTES + timedelta(seconds=var.VOTES_RATE_LIMIT) > datetime.now()):
        cli.msg(chan, nick+": Dit commando heeft een gebruikslimiet.")
        return    
    
    pl = var.list_players()
    
    if nick in pl:
        var.LAST_VOTES = datetime.now()    
        
    if not var.VOTES.values():
        msg = nick+": Nog geen stemmen."
        if nick in pl:
            var.LAST_VOTES = None # reset
    else:
        votelist = ["{0}: {1} ({2})".format(votee,
                                            len(var.VOTES[votee]),
                                            " ".join(var.VOTES[votee]))
                    for votee in var.VOTES.keys()]
        msg = "{0}: {1}".format(nick, ", ".join(votelist))
        
    if nick in pl:
        cli.msg(chan, msg)
    else:
        cli.notice(nick, msg)

    pl = var.list_players()
    avail = len(pl) - len(var.WOUNDED)
    votesneeded = avail // 2 + 1
    the_message = ("{0}: \u0002{1}\u0002 spelers, \u0002{2}\u0002 stemmen "+
                   "nodig om te elimineren, \u0002{3}\u0002 spelers beschikbaar " +
                   "om te stemmen.").format(nick, len(pl), votesneeded, avail)
    if nick in pl:
        cli.msg(chan, the_message)
    else:
        cli.notice(nick, the_message)



def chk_traitor(cli):
    for tt in var.ROLES["verrader"]:
        var.ROLES["wolf"].append(tt)
        var.ROLES["verrader"].remove(tt)
        pm(cli, tt, ('HOOOOOOOOOWL. Jij bent veranderd in een... wolf!\n'+
                     'Het is aan jou om je gesneuvelde soortgenoten te wreken!'))



def stop_game(cli, winner = ""):
    chan = botconfig.CHANNEL
    if var.DAY_START_TIME:
        now = datetime.now()
        td = now - var.DAY_START_TIME
        var.DAY_TIMEDELTA += td
    if var.NIGHT_START_TIME:
        now = datetime.now()
        td = now - var.NIGHT_START_TIME
        var.NIGHT_TIMEDELTA += td

    daymin, daysec = var.DAY_TIMEDELTA.seconds // 60, var.DAY_TIMEDELTA.seconds % 60
    nitemin, nitesec = var.NIGHT_TIMEDELTA.seconds // 60, var.NIGHT_TIMEDELTA.seconds % 60
    total = var.DAY_TIMEDELTA + var.NIGHT_TIMEDELTA
    tmin, tsec = total.seconds // 60, total.seconds % 60
    gameend_msg = ("Spel duurde \u0002{0:0>2}:{1:0>2}\u0002. " +
                   "\u0002{2:0>2}:{3:0>2}\u0002 was dag. " +
                   "\u0002{4:0>2}:{5:0>2}\u0002 was nacht. ").format(tmin, tsec,
                                                                     daymin, daysec,
                                                                     nitemin, nitesec)
    cli.msg(chan, gameend_msg)
    var.LOGGER.logMessage(gameend_msg.replace("\02", "")+"\n")
    var.LOGGER.logBare("DAY", "TIME", str(var.DAY_TIMEDELTA.seconds))
    var.LOGGER.logBare("NIGHT", "TIME", str(var.NIGHT_TIMEDELTA.seconds))
    var.LOGGER.logBare("GAME", "TIME", str(total.seconds))

    roles_msg = []
    
    var.ORIGINAL_ROLES["vervloekte burger"] = var.CURSED  # A hack
    var.ORIGINAL_ROLES["kanonnier"] = list(var.GUNNERS.keys())

    lroles = list(var.ORIGINAL_ROLES.keys())
    lroles.remove("wolf")
    lroles.insert(0, "wolf")   # picky, howl consistency
    
    for role in lroles:
        if len(var.ORIGINAL_ROLES[role]) == 0 or role == "burger":
            continue
        playersinrole = list(var.ORIGINAL_ROLES[role])
        for i,plr in enumerate(playersinrole):
            if plr.startswith("(dced)"):  # don't care about it here
                playersinrole[i] = plr[6:]
        if len(playersinrole) == 2:
            msg = "De {1} waren \u0002{0[0]}\u0002 en \u0002{0[1]}\u0002."
            roles_msg.append(msg.format(playersinrole, var.plural(role)))
        elif len(playersinrole) == 1:
            roles_msg.append("De {1} was \u0002{0[0]}\u0002.".format(playersinrole,
                                                                      role))
        else:
            msg = "De {2} waren {0}, en \u0002{1}\u0002."
            nickslist = ["\u0002"+x+"\u0002" for x in playersinrole[0:-1]]
            roles_msg.append(msg.format(", ".join(nickslist),
                                                  playersinrole[-1],
                                                  var.plural(role)))
    cli.msg(chan, " ".join(roles_msg))

    plrl = []
    for role,ppl in var.ORIGINAL_ROLES.items():
        for x in ppl:
            plrl.append((x, role))
    
    var.LOGGER.saveToFile()
    
    for plr, rol in plrl:
        #if plr not in var.USERS.keys():  # he died TODO: when a player leaves, count the game as lost for him
        #    if plr in var.DEAD_USERS.keys():
        #        acc = var.DEAD_USERS[plr]["account"]
        #    else:
        #        continue  # something wrong happened
        #else:
        if plr.startswith("(dced)") and plr[6:] in var.DCED_PLAYERS.keys():
            acc = var.DCED_PLAYERS[plr[6:]]["account"]
        elif plr in var.PLAYERS.keys():
            acc = var.PLAYERS[plr]["account"]
        else:
            continue  #probably fjoin'd fake

        if acc == "*":
            continue  # not logged in during game start
        # determine if this player's team won
        if plr in (var.ORIGINAL_ROLES["wolf"] + var.ORIGINAL_ROLES["verrader"] +
                   var.ORIGINAL_ROLES["weerweerkraai"]):  # the player was wolf-aligned
            if winner == "wolven":
                won = True
            elif winner == "burgers":
                won = False
            else:
                break  # abnormal game stop
        else:
            if winner == "wolven":
                won = False
            elif winner == "burgers":
                won = True
            else:
                break
                
        iwon = won and plr in var.list_players()  # survived, team won = individual win
                
        var.update_role_stats(acc, rol, won, iwon)
    
    reset(cli)
    
    # This must be after reset(cli)
    if var.AFTER_FLASTGAME:
        var.AFTER_FLASTGAME()
        var.AFTER_FLASTGAME = None
    if var.ADMIN_TO_PING:  # It was an flastgame
        cli.msg(chan, "PING! " + var.ADMIN_TO_PING)
        var.ADMIN_TO_PING = None
    
    return True

def chk_win(cli):
    """ Returns True if someone won """
    
    chan = botconfig.CHANNEL
    lpl = len(var.list_players())
    
    if lpl == 0:
        cli.msg(chan, "Er zijn geen spelers meer. Het spel is gestopt.")
        reset(cli)
        return True
        
    if var.PHASE == "join":
        return False
        
        
    lwolves = (len(var.ROLES["wolf"])+
               len(var.ROLES["verrader"])+
               len(var.ROLES["weerweerkraai"]))
    if var.PHASE == "day":
        lpl -= len([x for x in var.WOUNDED if x not in var.ROLES["verrader"]])
        lwolves -= len([x for x in var.WOUNDED if x in var.ROLES["verrader"]])
    
    if lwolves == lpl / 2:
        cli.msg(chan, ("Game over! Er zijn evenveel wolven als burgers."+
                       "De wolven eten iedereen op en winnen het spel."))
        var.LOGGER.logMessage(("Game over! Er zijn evenveel wolven als burgers."+
                               "De wolven eten iedereen op en winnen het spel."))
        village_win = False
        var.LOGGER.logBare("WOLVEN", "WIN")
    elif lwolves > lpl / 2:
        cli.msg(chan, ("Game over! Er zijn meer wolven dan burgers."+
                       "De wolven eten iedereen op en winnen het spel."))
        var.LOGGER.logMessage(("Game over! Er zijn evenveel wolven als burgers."+
                               "De wolven eten iedereen op en winnen het spel."))
        village_win = False
        var.LOGGER.logBare("WOLVEN", "WIN")
    elif (not var.ROLES["wolf"] and
          not var.ROLES["verrader"] and
          not var.ROLES["weerweerkraai"]):
        cli.msg(chan, ("Game over! Alle wolven zijn dood! De burgers "+
                       "filleren ze, BBQ ze, en hebben een stevige maaltijd."))
        var.LOGGER.logMessage(("Game over! Alle wolven zijn dood! De burgers "+
                               "filleren ze, BBQ ze, en hebben een stevige maaltijd."))
        village_win = True
        var.LOGGER.logBare("BURGERS", "WIN")
    elif (not var.ROLES["wolf"] and not 
          var.ROLES["weerweerkraai"] and var.ROLES["verrader"]):
        for t in var.ROLES["verrader"]:
            var.LOGGER.logBare(t, "TRANSFORM")
        chk_traitor(cli)
        cli.msg(chan, ('\u0002De burgers, tijdens het festijn, zijn bang '+
                       'ze horen een luide huil. De wolven zijn '+
                       'niet weg!\u0002'))
        var.LOGGER.logMessage(('De burgers, tijdens het festijn, zijn bang '+
                               'ze horen een luide huil. De wolven zijn '+
                               'niet weg!'))
        return chk_win(cli)
    else:
        return False
    stop_game(cli, "burgers" if village_win else "wolven")
    return True





def del_player(cli, nick, forced_death = False, devoice = True):
    """
    Returns: False if one side won.
    arg: forced_death = True when lynched or when the seer/wolf both don't act
    """
    t = time.time()  #  time
    
    var.LAST_STATS = None # reset
    var.LAST_VOTES = None
    
    with var.GRAVEYARD_LOCK:
        if not var.GAME_ID or var.GAME_ID > t:
            #  either game ended, or a new game has started.
            return False
        cmode = []
        if devoice:
            cmode.append(("-v", nick))
        var.del_player(nick)
        ret = True
        if var.PHASE == "join":
            # Died during the joining process as a person
            mass_mode(cli, cmode)
            return not chk_win(cli)
        if var.PHASE != "join" and ret:
            # Died during the game, so quiet!
            if not is_fake_nick(nick):
                cmode.append(("+q", nick+"!*@*"))
            mass_mode(cli, cmode)
            if nick not in var.DEAD:
                var.DEAD.append(nick)
            ret = not chk_win(cli)
        if var.PHASE in ("nacht", "dag") and ret:
            # remove him from variables if he is in there
            for a,b in list(var.KILLS.items()):
                if b == nick:
                    del var.KILLS[a]
                elif a == nick:
                    del var.KILLS[a]
            for x in (var.OBSERVED, var.HVISITED, var.GUARDED):
                keys = list(x.keys())
                for k in keys:
                    if k == nick:
                        del x[k]
                    elif x[k] == nick:
                        del x[k]
            if nick in var.DISCONNECTED:
                del var.DISCONNECTED[nick]
        if var.PHASE == "dag" and not forced_death and ret:  # didn't die from lynching
            if nick in var.VOTES.keys():
                del var.VOTES[nick]  #  Delete other people's votes on him
            for k in list(var.VOTES.keys()):
                if nick in var.VOTES[k]:
                    var.VOTES[k].remove(nick)
                    if not var.VOTES[k]:  # no more votes on that guy
                        del var.VOTES[k]
                    break # can only vote once
                    
            if nick in var.WOUNDED:
                var.WOUNDED.remove(nick)
            chk_decision(cli)
        elif var.PHASE == "nacht" and ret:
            chk_nightdone(cli)
        return ret  


def reaper(cli, gameid):
    # check to see if idlers need to be killed.
    var.IDLE_WARNED = []
    chan = botconfig.CHANNEL
    
    while gameid == var.GAME_ID:
        with var.GRAVEYARD_LOCK:
            if var.WARN_IDLE_TIME or var.KILL_IDLE_TIME:  # only if enabled
                to_warn = []
                to_kill = []
                for nick in var.list_players():
                    lst = var.LAST_SAID_TIME.get(nick, var.GAME_START_TIME)
                    tdiff = datetime.now() - lst
                    if (tdiff > timedelta(seconds=var.WARN_IDLE_TIME) and
                                            nick not in var.IDLE_WARNED):
                        if var.WARN_IDLE_TIME:
                            to_warn.append(nick)
                        var.IDLE_WARNED.append(nick)
                        var.LAST_SAID_TIME[nick] = (datetime.now() -
                            timedelta(seconds=var.WARN_IDLE_TIME))  # Give him a chance
                    elif (tdiff > timedelta(seconds=var.KILL_IDLE_TIME) and
                        nick in var.IDLE_WARNED):
                        if var.KILL_IDLE_TIME:
                            to_kill.append(nick)
                    elif (tdiff < timedelta(seconds=var.WARN_IDLE_TIME) and
                        nick in var.IDLE_WARNED):
                        var.IDLE_WARNED.remove(nick)  # he saved himself from death
                for nck in to_kill:
                    if nck not in var.list_players():
                        continue
                    cli.msg(chan, ("\u0002{0}\u0002 is niet opgestaan "+
                        "voor een erg lange tijd. Hij/zij is nu dood verklaard. "+
                        "Hij/zij was een \u0002{1}\u0002.").format(nck, var.get_role(nck)))
                    if not del_player(cli, nck):
                        return
                pl = var.list_players()
                x = [a for a in to_warn if a in pl]
                if x:
                    cli.msg(chan, ("{0}: \u0002Je Bent Idle voor een tijdje. "+
                                   "Doe actief mee of je word binnenkort "+
                                   "dood verklaard.\u0002").format(", ".join(x)))
            for dcedplayer in list(var.DISCONNECTED.keys()):
                _, timeofdc, what = var.DISCONNECTED[dcedplayer]
                if what == "quit" and (datetime.now() - timeofdc) > timedelta(seconds=var.QUIT_GRACE_TIME):
                    cli.msg(chan, ("\02{0}\02 is gestorven door een fatale aanvan van wilde dieren. "+
                                   "Hij/zij was een \02{1}\02.").format(dcedplayer, var.get_role(dcedplayer)))
                    if not del_player(cli, dcedplayer, devoice = False):
                        return
                elif what == "part" and (datetime.now() - timeofdc) > timedelta(seconds=var.PART_GRACE_TIME):
                    cli.msg(chan, ("\02{0}\02 is gestorven door het eten van giftige bessen. "+
                                   "Hij/zij was een \02{1}\02.").format(dcedplayer, var.get_role(dcedplayer)))
                    if not del_player(cli, dcedplayer, devoice = False):
                        return
        time.sleep(10)



@cmd("")  # update last said
def update_last_said(cli, nick, chan, rest):
    if var.PHASE not in ("join", "geen"):
        var.LAST_SAID_TIME[nick] = datetime.now()
    
    if var.PHASE not in ("geen", "join"):
        var.LOGGER.logChannelMessage(nick, rest)



@hook("join")
def on_join(cli, raw_nick, chan, acc="*", rname=""):
    nick,m,u,cloak = parse_nick(raw_nick)
    if nick not in var.USERS.keys() and nick != botconfig.NICK:
        var.USERS[nick] = dict(cloak=cloak,account=acc)
    with var.GRAVEYARD_LOCK:
        if nick in var.DISCONNECTED.keys():
            clk = var.DISCONNECTED[nick][0]
            if cloak == clk:
                cli.mode(chan, "+v", nick, nick+"!*@*")
                del var.DISCONNECTED[nick]
                
                cli.msg(chan, "\02{0}\02 is teruggekeerd naar het dorp.".format(nick))
                for r,rlist in var.ORIGINAL_ROLES.items():
                    if "(dced)"+nick in rlist:
                        rlist.remove("(dced)"+nick)
                        rlist.append(nick)
                        break
                if nick in var.DCED_PLAYERS.keys():
                    var.PLAYERS[nick] = var.DCED_PLAYERS.pop(nick)

@cmd("goat")
def goat(cli, nick, chan, rest):
    """Use a goat to interact with anyone in the channel during the day"""
    if var.PHASE in ("geen", "join"):
        cli.notice(nick, "Er is nu geen spel bezig.")
        return
    elif nick not in var.list_players() or nick in var.DISCONNECTED.keys():
        cli.notice(nick, "Je bent nu niet aan het spelen.")
        return
    if var.PHASE != "dag":
        cli.notice(nick, "Dat kun je alleen overdag doen.")
        return
    if var.GOATED:
        cli.notice(nick, "Je kunt dat maar een keer per dag doen.")
        return
    ul = list(var.USERS.keys())
    ull = [x.lower() for x in ul]
    rest = re.split(" +",rest)[0].strip().lower()
    if not rest:
        cli.notice(nick, "Niet genoeg parameters.")
        return
    matches = 0
    for player in ull:
        if rest == player:
            victim = player
            break
        if player.startswith(rest):
            victim = player
            matches += 1
    else:
        if matches != 1:
            pm(cli, nick,"\u0002{0}\u0002 is niet in dit kanaal.".format(rest))
            return
    victim = ul[ull.index(victim)]
    cli.msg(botconfig.CHANNEL, ("\u0002{0}\u0002's geit loopt langs "+
                                "en schopt \u0002{1}\u0002.").format(nick,
                                                                     victim))
    var.LOGGER.logMessage("{0}'s geit loopt langs en schopt {1}.".format(nick, victim))
    var.GOATED = True
    
    

@hook("nick")
def on_nick(cli, prefix, nick):
    prefix,u,m,cloak = parse_nick(prefix)
    chan = botconfig.CHANNEL

    if prefix in var.USERS:
        var.USERS[nick] = var.USERS.pop(prefix)
        
    if prefix == var.ADMIN_TO_PING:
        var.ADMIN_TO_PING = nick

    # for k,v in list(var.DEAD_USERS.items()):
        # if prefix == k:
            # var.DEAD_USERS[nick] = var.DEAD_USERS[k]
            # del var.DEAD_USERS[k]

    if prefix in var.list_players() and prefix not in var.DISCONNECTED.keys():
        r = var.ROLES[var.get_role(prefix)]
        r.append(nick)
        r.remove(prefix)

        if var.PHASE in ("nacht", "dag"):
            for k,v in var.ORIGINAL_ROLES.items():
                if prefix in v:
                    var.ORIGINAL_ROLES[k].remove(prefix)
                    var.ORIGINAL_ROLES[k].append(nick)
                    break
            for k,v in list(var.PLAYERS.items()):
                if prefix == k:
                    var.PLAYERS[nick] = var.PLAYERS[k]
                    del var.PLAYERS[k]
            if prefix in var.GUNNERS.keys():
                var.GUNNERS[nick] = var.GUNNERS.pop(prefix)
            if prefix in var.CURSED:
                var.CURSED.append(nick)
                var.CURSED.remove(prefix)
            for dictvar in (var.HVISITED, var.OBSERVED, var.GUARDED, var.KILLS):
                kvp = []
                for a,b in dictvar.items():
                    if a == prefix:
                        a = nick
                    if b == prefix:
                        b = nick
                    kvp.append((a,b))
                dictvar.update(kvp)
                if prefix in dictvar.keys():
                    del dictvar[prefix]
            if prefix in var.SEEN:
                var.SEEN.remove(prefix)
                var.SEEN.append(nick)
            with var.GRAVEYARD_LOCK:  # to be safe
                if prefix in var.LAST_SAID_TIME.keys():
                    var.LAST_SAID_TIME[nick] = var.LAST_SAID_TIME.pop(prefix)
                if prefix in var.IDLE_WARNED:
                    var.IDLE_WARNED.remove(prefix)
                    var.IDLE_WARNED.append(nick)

        if var.PHASE == "dag":
            if prefix in var.WOUNDED:
                var.WOUNDED.remove(prefix)
                var.WOUNDED.append(nick)
            if prefix in var.INVESTIGATED:
                var.INVESTIGATED.remove(prefix)
                var.INVESTIGATED.append(prefix)
            if prefix in var.VOTES:
                var.VOTES[nick] = var.VOTES.pop(prefix)
            for v in var.VOTES.values():
                if prefix in v:
                    v.remove(prefix)
                    v.append(nick)

    # Check if he was DC'ed
    if var.PHASE in ("nacht", "dag"):
        with var.GRAVEYARD_LOCK:
            if nick in var.DISCONNECTED.keys():
                clk = var.DISCONNECTED[nick][0]
                if cloak == clk:
                    cli.mode(chan, "+v", nick, nick+"!*@*")
                    del var.DISCONNECTED[nick]
                    
                    cli.msg(chan, ("\02{0}\02 is terug gekeerd naar "+
                                   "het dorp.").format(nick))

def leave(cli, what, nick, why=""):
    nick, _, _, cloak = parse_nick(nick)
        
    if why and why == botconfig.CHANGING_HOST_QUIT_MESSAGE:
        return
    if var.PHASE == "geen":
        return
    if nick in var.PLAYERS:
        # must prevent double entry in var.ORIGINAL_ROLES
        for r,rlist in var.ORIGINAL_ROLES.items():
            if nick in rlist:
                var.ORIGINAL_ROLES[r].remove(nick)
                var.ORIGINAL_ROLES[r].append("(dced)"+nick)
                break
        var.DCED_PLAYERS[nick] = var.PLAYERS.pop(nick)
    if nick not in var.list_players() or nick in var.DISCONNECTED.keys():
        return
    
        
    #  the player who just quit was in the game
    killhim = True
    if what == "part" and (not var.PART_GRACE_TIME or var.PHASE == "join"):
        msg = ("\02{0}\02 is gestorven door het eten van giftige bessen. "+
               "Hij/zij was een \02{1}\02.").format(nick, var.get_role(nick))
    elif what == "quit" and (not var.QUIT_GRACE_TIME or var.PHASE == "join"):
        msg = ("\02{0}\02 is gestorven door een fatale aan van van wilde dieren. "+
               "Hij/zij was een \02{1}\02.").format(nick, var.get_role(nick))
    elif what != "kick":
        msg = "\u0002{0}\u0002 is vermist.".format(nick)
        killhim = False
    else:
        msg = ("\02{0}\02 is gestorven door van een klif te vallen. "+
               "Hij/zij was een \02{1}\02.").format(nick, var.get_role(nick))
    cli.msg(botconfig.CHANNEL, msg)
    var.LOGGER.logMessage(msg.replace("\02", ""))
    if killhim:
        del_player(cli, nick)
    else:
        var.DISCONNECTED[nick] = (cloak, datetime.now(), what)

#Functions decorated with hook do not parse the nick by default
hook("part")(lambda cli, nick, *rest: leave(cli, "part", nick))
hook("quit")(lambda cli, nick, *rest: leave(cli, "quit", nick, rest[0]))
hook("kick")(lambda cli, nick, *rest: leave(cli, "kick", rest[1]))


@cmd("quit", "leave")
def leave_game(cli, nick, chan, rest):
    """Quits the game."""
    if var.PHASE == "geen":
        cli.notice(nick, "Er is nu geen spel bezig.")
        return
    if nick not in var.list_players() or nick in var.DISCONNECTED.keys():  # not playing
        cli.notice(nick, "Je doet nu niet mee aan het spel.")
        return
    cli.msg(botconfig.CHANNEL, ("\02{0}\02 is gestorven aan een onbekende ziekte. "+
                                "Hij/zij was een \02{1}\02.").format(nick, var.get_role(nick)))
    var.LOGGER.logMessage(("{0} is gestorven aan een onbekende ziekte. "+
                           "Hij/zij was een {1}.").format(nick, var.get_role(nick)))
    del_player(cli, nick)



def begin_day(cli):
    chan = botconfig.CHANNEL

    # Reset nighttime variables
    var.KILLS = {}  # nicknames of kill victim
    var.GUARDED = ""
    var.KILLER = ""  # nickname of who chose the victim
    var.SEEN = []  # list of seers that have had visions
    var.OBSERVED = {}  # those whom werecrows have observed
    var.HVISITED = {}
    var.GUARDED = {}

    msg = ("De burgers moeten nu stemmen wie ze willen elimineren. "+
           'gebruik "{0}lynch <nick>" om je stem door te geven. {1} stemmen '+
           'zijn nodig om iemand te elimineren.').format(botconfig.CMD_CHAR, len(var.list_players()) // 2 + 1)
    cli.msg(chan, msg)
    var.LOGGER.logMessage(msg)
    var.LOGGER.logBare("DAY", "BEGIN")

    if var.DAY_TIME_LIMIT_WARN > 0:  # Time limit enabled
        var.DAY_ID = time.time()
        t = threading.Timer(var.DAY_TIME_LIMIT_WARN, hurry_up, [cli, var.DAY_ID, False])
        var.TIMERS["day_warn"] = t
        t.daemon = True
        t.start()

def night_warn(cli, gameid):
    if gameid != var.NIGHT_ID:
        return
    
    if var.PHASE == "day":
        return
        
    cli.msg(botconfig.CHANNEL, ("\02A De burgers worden wakker en het valt ze op " +
                                "dat het buiten nogsteeds donker is. " +
                                "De nacht is bijna voorbij en er zijn " +
                                "nogsteeds geluiden te horen in het dorp.\02"))

def transition_day(cli, gameid=0):
    if gameid:
        if gameid != var.NIGHT_ID:
            return
    var.NIGHT_ID = 0
    
    if var.PHASE == "dag":
        return
    
    var.PHASE = "dag"
    var.GOATED = False
    chan = botconfig.CHANNEL
    
    # Reset daytime variables
    var.VOTES = {}
    var.INVESTIGATED = []
    var.WOUNDED = []
    var.DAY_START_TIME = datetime.now()

    if (not len(var.SEEN)+len(var.KILLS)+len(var.OBSERVED) # neither seer nor wolf acted
            and var.FIRST_NIGHT and var.ROLES["ziener"] and not botconfig.DEBUG_MODE):
        cli.msg(botconfig.CHANNEL, "\02De wolven zijn allemaal gestorven door een onbekende ziekte.\02")
        for x in var.ROLES["wolf"]+var.ROLES["weerweerkraai"]+var.ROLES["verrader"]:
            if not del_player(cli, x, True):
                return
    
    var.FIRST_NIGHT = False

    td = var.DAY_START_TIME - var.NIGHT_START_TIME
    var.NIGHT_START_TIME = None
    var.NIGHT_TIMEDELTA += td
    min, sec = td.seconds // 60, td.seconds % 60

    found = {}
    for v in var.KILLS.values():
        if v in found:
            found[v] += 1
        else:
            found[v] = 1
    
    maxc = 0
    victim = ""
    dups = []
    for v, c in found.items():
        if c > maxc:
            maxc = c
            victim = v
            dups = []
        elif c == maxc:
            dups.append(v)

    if maxc:
        if dups:
            dups.append(victim)
            victim = random.choice(dups)
    
    message = [("Nacht duurde \u0002{0:0>2}:{1:0>2}\u0002. Het is nu dag. "+
               "De burgers worden wakker, dankbaar dat ze de nacht hebben overleeft, "+
               "en doorzoeken het dorp... ").format(min, sec)]
    dead = []
    crowonly = var.ROLES["weerweerkraai"] and not var.ROLES["wolf"]
    if victim:
        var.LOGGER.logBare(victim, "WOLVESVICTIM", *[y for x,y in var.KILLS.items() if x == victim])
    for crow, target in iter(var.OBSERVED.items()):
        if ((target in list(var.HVISITED.keys()) and var.HVISITED[target]) or  # if var.HVISITED[target] is None, harlot visited self
            target in var.SEEN+list(var.GUARDED.keys())):
            pm(cli, crow, ("Met dat de zon opgaat, zie je dat \u0002{0}\u0002 de hele nacht niet in "+
                          "zijn bed heeft gelegen, en je gaat vliegensvlug terug naar je huis.").format(target))
        else:
            pm(cli, crow, ("Met dat de zon opgaat, zie je dat \u0002{0}\u0002 de hele nacht "+
                          "heeft geslapen, en je gaat vliegensvlug terug naar je huis.").format(target))
    if victim in var.GUARDED.values():
        message.append(("\u0002{0}\u0002 is afgelopen nacht aangevalen door de wolven, maar gelukkig, "+
                        "de bescherm engel heeft hem/haar beschermd.").format(victim))
        victim = ""
    elif not victim:
        message.append(random.choice(var.NO_VICTIMS_MESSAGES) +
                    " Alle burgers hebben, wonder boven wonder, het overleeft.")
    elif victim in var.ROLES["onschuldige meisje"]:  # Attacked harlot, yay no kill
        if var.HVISITED.get(victim):
            message.append("De door de wolven gekozen slachtoffer was een onschuldige meisje, "+
                           "maar ze was niet thuis.")
    if victim and (victim not in var.ROLES["onschuldige meisje"] or   # not a harlot
                          not var.HVISITED.get(victim)):   # harlot stayed home
        message.append(("Het dode lichaam van \u0002{0}\u0002, een "+
                        "\u0002{1}\u0002, is gevonden. De nabestaanden rouwen om zijn/haar "+
                        "dood.").format(victim, var.get_role(victim)))
        dead.append(victim)
        var.LOGGER.logBare(victim, "KILLED")
    if victim in var.GUNNERS.keys() and var.GUNNERS[victim]:  # victim had bullets!
        if random.random() < var.GUNNER_KILLS_WOLF_AT_NIGHT_CHANCE:
            wc = var.ROLES["weerweerkraai"]
            for crow in wc:
                if crow in var.OBSERVED.keys():
                    wc.remove(crow)
            # don't kill off werecrows that observed
            deadwolf = random.choice(var.ROLES["wolf"]+wc)
            message.append(("Helaas, het slachtoffer, \02{0}\02, heeft een geweer met kogels en "+
                            "\02{1}\02, een \02{2}\02, is neergeschoten.").format(victim, deadwolf, var.get_role(deadwolf)))
            var.LOGGER.logBare(deadwolf, "KILLEDBYGUNNER")
            dead.append(deadwolf)
    if victim in var.HVISITED.values():  #  victim was visited by some harlot
        for hlt in var.HVISITED.keys():
            if var.HVISITED[hlt] == victim:
                message.append(("\02{0}\02, een \02onschuldige meisje\02, maakte de verkeerde beslissing "+
                                "door afgelopen nacht het huis van het slachtoffer te bezoeken en is "+
                                "nu gestorven.").format(hlt))
                dead.append(hlt)
    for harlot in var.ROLES["onschuldige meisje"]:
        if var.HVISITED.get(harlot) in var.ROLES["wolf"]+var.ROLES["weerweerkraai"]:
            message.append(("\02{0}\02, een \02onschuldige meisje\02, maakte de verkeerde beslissing door "+
                                "afgelopen nacht het huis van de wolf te bezoeken en is "+
                                "nu gestorven.").format(harlot))
            dead.append(harlot)
    for gangel in var.ROLES["bescherm engel"]:
        if var.GUARDED.get(gangel) in var.ROLES["wolf"]+var.ROLES["weerweerkraai"]:
            if victim == gangel:
                continue # already dead.
            r = random.random()
            if r < var.GUARDIAN_ANGEL_DIES_CHANCE:
                message.append(("\02{0}\02, een \02bescherm engel\02, "+
                                "maakte de verkeerde beslissing door afgelopen nacht een wolf "+
                                "te beschermen, hij/zij probeerde te ontkomen, maar het mislukte "+
                                "en is nu gestorven.").format(gangel))
                var.LOGGER.logBare(gangel, "KILLEDWHENGUARDINGWOLF")
                dead.append(gangel)
    cli.msg(chan, "\n".join(message))
    for msg in message:
        var.LOGGER.logMessage(msg.replace("\02", ""))
    for deadperson in dead:
        if not del_player(cli, deadperson):
            return
    
    if (var.WOLF_STEALS_GUN and victim in dead and 
        victim in var.GUNNERS.keys() and var.GUNNERS[victim] > 0):
        # victim has bullets
        guntaker = random.choice(var.ROLES["wolf"] + var.ROLES["weerweerkraai"] 
                                 + var.ROLES["verrader"])  # random looter
        numbullets = var.GUNNERS[victim]
        var.WOLF_GUNNERS[guntaker] = numbullets  # transfer bullets to him/her
        mmsg = ("tijdens het zoeken naar {2}'s eigendommen, Je vond " + 
                "een geweer geladen met {0} zilveren kogel{1}! " + 
                "Je kunt deze alleen overdag gebruiken. " +
                "Als je een wolf raakt, kan het zijn dat je hem perongeluk zal missen. " +
                "Als je een burger raakt, zal het waarschijnlijk zijn dat deze gewond raakt.")
        if numbullets == 1:
            mmsg = mmsg.format(numbullets, "", victim)
        else:
            mmsg = mmsg.format(numbullets, "s", victim)
        pm(cli, guntaker, mmsg)
        var.GUNNERS[victim] = 0  # just in case

            
    begin_day(cli)


def chk_nightdone(cli):
    if (len(var.SEEN) == len(var.ROLES["ziener"]) and  # Seers have seen.
        len(var.HVISITED.keys()) == len(var.ROLES["onschuldige meisje"]) and  # harlots have visited.
        len(var.GUARDED.keys()) == len(var.ROLES["bescherm engel"]) and  # guardians have guarded
        len(var.ROLES["weerweerkraai"]+var.ROLES["wolf"]) == len(var.KILLS)+len(var.OBSERVED) and
        var.PHASE == "nacht"):
        
        # check if wolves are actually agreeing
        if len(set(var.KILLS.values())) > 1:
            return
        
        for x, t in var.TIMERS.items():
            t.cancel()
        
        var.TIMERS = {}
        if var.PHASE == "nacht":  # Double check
            transition_day(cli)



@cmd("lynch", "vote")
def vote(cli, nick, chann_, rest):
    """Use this to vote for a candidate to be lynched"""
    chan = botconfig.CHANNEL
    
    if var.PHASE in ("geen", "join"):
        cli.notice(nick, "Er is geen spel bezig.")
        return
    elif nick not in var.list_players() or nick in var.DISCONNECTED.keys():
        cli.notice(nick, "Jij speelt momenteel niet mee.")
        return
    if var.PHASE != "dag":
        cli.notice(nick, ("Elimineren kan alleen overdag gedaan worden. "+
                          "Wacht tot de morgen is gekomen."))
        return
    if nick in var.WOUNDED:
        cli.msg(chan, ("{0}: Je bent gewond en moet rusten, "+
                      "daarom kun je vandaag niet stemmen.").format(nick))
        return
    pl = var.list_players()
    pl_l = [x.strip().lower() for x in pl]
    rest = re.split(" +",rest)[0].strip().lower()
    
    if not rest:
        cli.notice(nick, "Niet genoeg parameters.")
        return
    
    matches = 0
    for player in pl_l:
        if rest == player:
            target = player
            break
        if player.startswith(rest):
            target = player
            matches += 1
    else:
        if matches != 1:
            pm(cli, nick, "\u0002{0}\u0002 speelt niet mee.".format(rest))
            return
        
    voted = pl[pl_l.index(target)]
    lcandidates = list(var.VOTES.keys())
    for voters in lcandidates:  # remove previous vote
        if nick in var.VOTES[voters]:
            var.VOTES[voters].remove(nick)
            if not var.VOTES.get(voters) and voters != voted:
                del var.VOTES[voters]
            break
    if voted not in var.VOTES.keys():
        var.VOTES[voted] = [nick]
    else:
        var.VOTES[voted].append(nick)
    cli.msg(chan, ("\u0002{0}\u0002 stemmen voor "+
                   "\u0002{1}\u0002.").format(nick, voted))
    var.LOGGER.logMessage("{0} stemmen voor {1}.".format(nick, voted))
    var.LOGGER.logBare(voted, "VOTED", nick)
    
    var.LAST_VOTES = None # reset
    
    chk_decision(cli)



@cmd("retract")
def retract(cli, nick, chann_, rest):
    """Takes back your vote during the day (for whom to lynch)"""
    
    chan = botconfig.CHANNEL
    
    if var.PHASE in ("geen", "join"):
        cli.notice(nick, "Er is nu geen spel bezig.")
        return
    elif nick not in var.list_players() or nick in var.DISCONNECTED.keys():
        cli.notice(nick, "Jij speelt nu niet mee.")
        return
        
    if var.PHASE != "dag":
        cli.notice(nick, ("Elimineren kan alleen overdag gedaan worden. "+
                          "Wacht tot de morgen is gekomen."))
        return

    candidates = var.VOTES.keys()
    for voter in list(candidates):
        if nick in var.VOTES[voter]:
            var.VOTES[voter].remove(nick)
            if not var.VOTES[voter]:
                del var.VOTES[voter]
            cli.msg(chan, "\u0002{0}\u0002 trekt zijn/haar stem terug.".format(nick))
            var.LOGGER.logBare(voter, "RETRACT", nick)
            var.LOGGER.logMessage("{0} trekt zijn/haar stem terug.".format(nick))
            var.LAST_VOTES = None # reset
            break
    else:
        cli.notice(nick, "Je hebt nog niet gestemd.")



@cmd("shoot")
def shoot(cli, nick, chann_, rest):
    """Use this to fire off a bullet at someone in the day if you have bullets"""
    
    chan = botconfig.CHANNEL
    if var.PHASE in ("geen", "join"):
        cli.notice(nick, "Er is nu geen spel bezig.")
        return
    elif nick not in var.list_players() or nick in var.DISCONNECTED.keys():
        cli.notice(nick, "Jij speelt nu niet mee.")
        return
        
    if var.PHASE != "dag":
        cli.notice(nick, ("Schieten mag alleen overdag. "+
                          "Wacht tot de morgen is gekomen."))
        return
    if not (nick in var.GUNNERS.keys() or nick in var.WOLF_GUNNERS.keys()):
        pm(cli, nick, "Je hebt geen geweer.")
        return
    elif ((nick in var.GUNNERS.keys() and not var.GUNNERS[nick]) or
          (nick in var.WOLF_GUNNERS.keys() and not var.WOLF_GUNNERS[nick])):
        pm(cli, nick, "Je kogels zijn op.")
        return
    victim = re.split(" +",rest)[0].strip().lower()
    if not victim:
        cli.notice(nick, "Niet genoeg parameters")
        return
    pl = var.list_players()
    pll = [x.lower() for x in pl]
    matches = 0
    for player in pll:
        if victim == player:
            target = player
            break
        if player.startswith(victim):
            target = player
            matches += 1
    else:
        if matches != 1:
            pm(cli, nick, "\u0002{0}\u0002 speelt niet mee met dit spel.".format(victim))
            return
    victim = pl[pll.index(target)]
    if victim == nick:
        cli.notice(nick, "Je houd het geweer verkeerdom vast.")
        return
    
    wolfshooter = nick in var.ROLES["wolf"]+var.ROLES["weerweerkraai"]+var.ROLES["verrader"]
    
    if wolfshooter and nick in var.WOLF_GUNNERS:
        var.WOLF_GUNNERS[nick] -= 1
    else:
        var.GUNNERS[nick] -= 1
    
    rand = random.random()
    if nick in var.ROLES["dronken burger"]:
        chances = var.DRUNK_GUN_CHANCES
    else:
        chances = var.GUN_CHANCES
    
    wolfvictim = victim in var.ROLES["wolf"]+var.ROLES["weerweerkraai"]
    if rand <= chances[0] and not (wolfshooter and wolfvictim):  # didn't miss or suicide
        # and it's not a wolf shooting another wolf
        
        cli.msg(chan, ("\u0002{0}\u0002 schiet op \u0002{1}\u0002 met "+
                       "een zilveren kogel").format(nick, victim))
        var.LOGGER.logMessage("{0} schiet op {1} met een zilveren kogel!".format(nick, victim))
        victimrole = var.get_role(victim)
        if victimrole in ("wolf", "weerweerkraai"):
            cli.msg(chan, ("\u0002{0}\u0002 is een wolf, en is gedood door "+
                           "een zilveren kogel.").format(victim))
            var.LOGGER.logMessage(("{0} is een wolf,en is gedood door "+
                            "een zilveren kogel.").format(victim))
            if not del_player(cli, victim):
                return
        elif random.random() <= var.MANSLAUGHTER_CHANCE:
            cli.msg(chan, ("\u0002{0}\u0002 is geen wolf "+
                           "maar is perongeluk fataal gewond geraakt.").format(victim))
            cli.msg(chan, "Hij/zij bleek een \u0002{0}\u0002 te zijn.".format(victimrole))
            var.LOGGER.logMessage("{0} is geen wolf en is fataal gewond geraakt.".format(victim))
            var.LOGGER.logMessage("Hij/zij was een {0}.".format(victimrole))
            if not del_player(cli, victim):
                return
        else:
            cli.msg(chan, ("\u0002{0}\u0002 is een burger en is gewond geraakt maar "+
                          "zal volledig hestellen. Hij/zij moet de hele dag "+
                          "rust houden.").format(victim))
            var.LOGGER.logMessage(("{0} is een burger en is gewond geraakt maar "+
                            "zal volledig hestellen. Hij/zij moet de hele dag "+
                            "rust houden").format(victim))
            if victim not in var.WOUNDED:
                var.WOUNDED.append(victim)
            lcandidates = list(var.VOTES.keys())
            for cand in lcandidates:  # remove previous vote
                if victim in var.VOTES[cand]:
                    var.VOTES[cand].remove(victim)
                    if not var.VOTES.get(cand):
                        del var.VOTES[cand]
                    break
            chk_decision(cli)
            chk_win(cli)
    elif rand <= chances[0] + chances[1]:
        cli.msg(chan, "\u0002{0}\u0002 is een slechte schutter. Hij/zij mist!".format(nick))
        var.LOGGER.logMessage("{0} is een slechte schutter. Hij/zij mist!".format(nick))
    else:
        cli.msg(chan, ("\u0002{0}\u0002 moet zijn/haar geweer vaker schoonmaken. "+
                      "Het geweer explodeerde en dode hem/haar!").format(nick))
        cli.msg(chan, "Hij/zij was een \u0002{0}\u0002.".format(var.get_role(nick)))
        var.LOGGER.logMessage(("{0} moet zijn/haar geweer vaker schoonmakenn. "+
                        "Het geweer explodeerde en dode hem/haar!").format(nick))
        var.LOGGER.logMessage("Hij/zij was een {0}.".format(var.get_role(nick)))
        if not del_player(cli, nick):
            return  # Someone won.



@pmcmd("kill")
def kill(cli, nick, rest):
    if var.PHASE in ("geen", "join"):
        cli.notice(nick, "Er is geen spel bezig.")
        return
    elif nick not in var.list_players() or nick in var.DISCONNECTED.keys():
        cli.notice(nick, "Jij doet nu niet mee aan het spel.")
        return
    role = var.get_role(nick)
    if role == "verrader":
        return  # they do this a lot.
    if role not in ('wolf', 'weerweerkraai'):
        pm(cli, nick, "Alleen een wolf mag dit commando gebruiken.")
        return
    if var.PHASE != "nacht":
        pm(cli, nick, "Je kunt alleen 's nachts iemand vermoorden.")
        return
    victim = re.split(" +",rest)[0].strip().lower()
    if not victim:
        pm(cli, nick, "Niet genoeg parameters")
        return
    if role == "weerweerkraai":  # Check if flying to observe
        if var.OBSERVED.get(nick):
            pm(cli, nick, ("Je bent al in een weerweerkraai veranderd; En daarom, "+
                           "ben je physiek niet in staat burgers te doden."))
            return
    pl = var.list_players()
    pll = [x.lower() for x in pl]
    
    matches = 0
    for player in pll:
        if victim == player:
            target = player
            break
        if player.startswith(victim):
            target = player
            matches += 1
    else:
        if matches != 1:
            pm(cli, nick, "\u0002{0}\u0002 speelt nu niet mee.".format(victim))
            return
    
    victim = pl[pll.index(target)]
    if victim == nick:
        pm(cli, nick, "Zelfmoord is slecht. Doe het niet.")
        return
    if victim in var.ROLES["wolf"]+var.ROLES["weerweerkraai"]:
        pm(cli, nick, "Je mag allen burgers doden, niet de andere wolven.")
        return
    var.KILLS[nick] = victim
    pm(cli, nick, "Jij hebt \u0002{0}\u0002 gekozen om te worden gedood.".format(victim))
    var.LOGGER.logBare(nick, "SELECT", victim)
    chk_nightdone(cli)


@pmcmd("guard", "protect", "save")
def guard(cli, nick, rest):
    if var.PHASE in ("geen", "join"):
        cli.notice(nick, "Er is geen spel bezig.")
        return
    elif nick not in var.list_players() or nick in var.DISCONNECTED.keys():
        cli.notice(nick, "Jij doet nu niet mee aan het spel.")
        return
    role = var.get_role(nick)
    if role != 'bescherm engel':
        pm(cli, nick, "Alleen een bescherm engel kan dit commando gebruiken.")
        return
    if var.PHASE != "nacht":
        pm(cli, nick, "Je kunt alleen 's nachts iemand beschermen.")
        return
    victim = re.split(" +",rest)[0].strip().lower()
    if not victim:
        pm(cli, nick, "Niet genoeg parameters")
        return
    if var.GUARDED.get(nick):
        pm(cli, nick, ("Je beschermd "+
                      "\u0002{0}\u0002 al.").format(var.GUARDED[nick]))
        return
    pl = var.list_players()
    pll = [x.lower() for x in pl]
    matches = 0
    for player in pll:
        if victim == player:
            target = player
            break
        if player.startswith(victim):
            target = player
            matches += 1
    else:
        if matches != 1:
            pm(cli, nick, "\u0002{0}\u0002 speelt nu niet mee.".format(victim))
            return
    victim = pl[pll.index(target)]
    if victim == nick:
        pm(cli, nick, "Je kunt jezelf niet beschermen.")
        return
    var.GUARDED[nick] = victim
    pm(cli, nick, "Je beschermd \u0002{0}\u0002 vannacht. Succes!".format(var.GUARDED[nick]))
    pm(cli, var.GUARDED[nick], "Je kunt rustig slapen vannacht, een bescherm engel beschermd je vannacht.")
    var.LOGGER.logBare(var.GUARDED[nick], "GUARDED", nick)
    chk_nightdone(cli)



@pmcmd("observe")
def observe(cli, nick, rest):
    if var.PHASE in ("geen", "join"):
        cli.notice(nick, "Er is geen spel bezig.")
        return
    elif nick not in var.list_players() or nick in var.DISCONNECTED.keys():
        cli.notice(nick, "Jij doet nu niet mee aan het spel.")
        return
    if not var.is_role(nick, "weerweerkraai"):
        pm(cli, nick, "Alleen een weerweerkraai kan dit commando gebruiken.")
        return
    if var.PHASE != "nacht":
        pm(cli, nick, "Je kunt alleen 's nachts in een weerweerkraai veranderen.")
        return
    victim = re.split(" +", rest)[0].strip().lower()
    if not victim:
        pm(cli, nick, "Niet genoeg parameters")
        return
    pl = var.list_players()
    pll = [x.lower() for x in pl]
    matches = 0
    for player in pll:
        if victim == player:
            target = player
            break
        if player.startswith(victim):
            target = player
            matches += 1
    else:
        if matches != 1:
            pm(cli, nick,"\u0002{0}\u0002 speelt nu niet mee.".format(victim))
            return
    victim = pl[pll.index(target)]
    if victim == nick.lower():
        pm(cli, nick, "Misschien moet je, inplaats van dit, iemand vermoorden.")
        return
    if nick in var.OBSERVED.keys():
        pm(cli, nick, "Je vliegt al naar \02{0}\02's huis.".format(var.OBSERVED[nick]))
        return
    if var.get_role(victim) in ("weerweerkraai", "verrader", "wolf"):
        pm(cli, nick, "Naar een huis van een andere wolf vliegen is verspilling van je tijd.")
        return
    var.OBSERVED[nick] = victim
    if nick in var.KILLS.keys():
        del var.KILLS[nick]
    pm(cli, nick, ("Je bent in een grote weerweerkraai veranderd enje begint te vliegen "+
                   "naarr \u0002{0}'s\u0002 huis. Je keert terug wanneer "+
                  "je goed hebt rondgekeken en de dag begint.").format(victim))
    var.LOGGER.logBare(victim, "OBSERVED", nick)



@pmcmd("id")
def investigate(cli, nick, rest):
    if var.PHASE in ("geen", "join"):
        cli.notice(nick, "Er is geen spel bezig.")
        return
    elif nick not in var.list_players() or nick in var.DISCONNECTED.keys():
        cli.notice(nick, "Jij doet nu niet mee aan het spel.")
        return
    if not var.is_role(nick, "rechercheur"):
        pm(cli, nick, "Alleen een rechercheur mag dit commando gebruiken.")
        return
    if var.PHASE != "dag":
        pm(cli, nick, "Aleen overdag kun je onderzoek doen naar mensen.")
        return
    if nick in var.INVESTIGATED:
        pm(cli, nick, "Je mag maar één persoon per ronde onderzoeken.")
        return
    victim = re.split(" +", rest)[0].strip().lower()
    if not victim:
        pm(cli, nick, "Niet genoeg parameters")
        return
    pl = var.list_players()
    pll = [x.lower() for x in pl]
    matches = 0
    for player in pll:
        if victim == player:
            target = player
            break
        if player.startswith(victim):
            target = player
            matches += 1
    else:
        if matches != 1:
            pm(cli, nick,"\u0002{0}\u0002 speelt nu niet mee.".format(victim))
            return
    victim = pl[pll.index(target)]

    var.INVESTIGATED.append(nick)
    pm(cli, nick, ("Het resultaat van je onderzoek is binnen. \u0002{0}\u0002"+
                   " is een... \u0002{1}\u0002!").format(victim, var.get_role(victim)))
    var.LOGGER.logBare(victim, "INVESTIGATED", nick)
    if random.random() < var.rechercheur_REVEALED_CHANCE:  # a 2/5 chance (should be changeable in settings)
        # Reveal his role!
        for badguy in var.ROLES["wolf"] + var.ROLES["weerweerkraai"] + var.ROLES["verrader"]:
            pm(cli, badguy, ("\u0002{0}\u0002 heeft perongeluk een papier laten vallen. Hier op staat "+
                            "dat hij/zij een rechercheur is!").format(nick))
        var.LOGGER.logBare(nick, "PAPERDROP")



@pmcmd("visit")
def hvisit(cli, nick, rest):
    if var.PHASE in ("geen", "join"):
        cli.notice(nick, "Er is geen spel bezig.")
        return
    elif nick not in var.list_players() or nick in var.DISCONNECTED.keys():
        cli.notice(nick, "Jij doet nu niet mee aan het spel.")
        return
    if not var.is_role(nick, "onschuldige meisje"):
        pm(cli, nick, "Alleen een onschuldige meisje kan dit commando gebruiken.")
        return
    if var.PHASE != "nacht":
        pm(cli, nick, "Je kunt alleen 's nachts iemand bezoeken.")
        return
    if var.HVISITED.get(nick):
        pm(cli, nick, ("Je brengt de nacht al door "+
                      "met \u0002{0}\u0002.").format(var.HVISITED[nick]))
        return
    victim = re.split(" +",rest)[0].strip().lower()
    if not victim:
        pm(cli, nick, "Niet genoeg parameters")
        return
    pll = [x.lower() for x in var.list_players()]
    matches = 0
    for player in pll:
        if victim == player:
            target = player
            break
        if player.startswith(victim):
            target = player
            matches += 1
    else:
        if matches != 1:
            pm(cli, nick,"\u0002{0}\u0002 speelt nu niet mee.".format(victim))
            return
    victim = var.list_players()[pll.index(target)]
    if nick == victim:  # Staying home
        var.HVISITED[nick] = None
        pm(cli, nick, "Je hebt er voor gekozen vanacht thuis te blijven.")
    else:
        var.HVISITED[nick] = victim
        pm(cli, nick, ("Je brengt de nacht door met \u0002{0}\u0002. "+
                      "Veel plezier!").format(var.HVISITED[nick]))
        pm(cli, var.HVISITED[nick], ("Je brengt de nacht door met \u0002{0}"+
                                     "\u0002. veel plezier!").format(nick))
        var.LOGGER.logBare(var.HVISITED[nick], "VISITED", nick)
    chk_nightdone(cli)


def is_fake_nick(who):
    return not(re.search("^[a-zA-Z\\\_\]\[`]([a-zA-Z0-9\\\_\]\[`]+)?", who)) or who.lower().endswith("serv")



@pmcmd("see")
def see(cli, nick, rest):
    if var.PHASE in ("geen", "join"):
        cli.notice(nick, "Er is geen spel bezig.")
        return
    elif nick not in var.list_players() or nick in var.DISCONNECTED.keys():
        cli.notice(nick, "Jij doet nu niet mee aan het spel.")
        return
    if not var.is_role(nick, "ziener"):
        pm(cli, nick, "Alleen een ziener mag dit commando gebruiken")
        return
    if var.PHASE != "nacht":
        pm(cli, nick, "Alleen 's nachts kun je visioenen hebben.")
        return
    if nick in var.SEEN:
        pm(cli, nick, "Je kunt maar één visioen per ronde hebben.")
        return
    victim = re.split(" +",rest)[0].strip().lower()
    pl = var.list_players()
    pll = [x.lower() for x in pl]
    if not victim:
        pm(cli, nick, "Niet genoeg parameters")
        return
    matches = 0
    for player in pll:
        if victim == player:
            target = player
            break
        if player.startswith(victim):
            target = player
            matches += 1
    else:
        if matches != 1:
            pm(cli, nick,"\u0002{0}\u0002 speelt nu niet mee.".format(victim))
            return
    victim = pl[pll.index(target)]
    if victim in var.CURSED:
        role = "wolf"
    elif var.get_role(victim) == "verrader":
        role = "burger"
    else:
        role = var.get_role(victim)
    pm(cli, nick, ("Je hebt een visioen. In deze visioen, "+
                    "zie je dat \u0002{0}\u0002 een "+
                    "\u0002{1}\u0002 is!").format(victim, role))
    var.SEEN.append(nick)
    var.LOGGER.logBare(victim, "SEEN", nick)
    chk_nightdone(cli)



@hook("featurelist")  # For multiple targets with PRIVMSG
def getfeatures(cli, nick, *rest):
    for r in rest:
        if r.startswith("TARGMAX="):
            x = r[r.index("PRIVMSG:"):]
            if "," in x:
                l = x[x.index(":")+1:x.index(",")]
            else:
                l = x[x.index(":")+1:]
            l = l.strip()
            if not l or not l.isdigit():
                continue
            else:
                var.MAX_PRIVMSG_TARGETS = int(l)
                break



def mass_privmsg(cli, targets, msg, notice = False):
    while targets:
        if len(targets) <= var.MAX_PRIVMSG_TARGETS:
            bgs = ",".join(targets)
            targets = ()
        else:
            bgs = ",".join(targets[0:var.MAX_PRIVMSG_TARGETS])
            targets = targets[var.MAX_PRIVMSG_TARGETS:]
        if not notice:
            cli.msg(bgs, msg)
        else:
            cli.notice(bgs, msg)
                
                

@pmcmd("")
def relay(cli, nick, rest):
    """Let the wolves talk to each other through the bot"""
    if var.PHASE not in ("nacht", "dag"):
        return

    badguys = var.ROLES["wolf"] + var.ROLES["verrader"] + var.ROLES["weerkraai"]
    if len(badguys) > 1:
        if nick in badguys:
            badguys.remove(nick)  #  remove self from list
        
            if rest.startswith("\01ACTION"):
                rest = rest[7:-1]
                mass_privmsg(cli, [guy for guy in badguys 
                    if (guy in var.PLAYERS and
                        var.PLAYERS[guy]["cloak"] not in var.SIMPLE_NOTIFY)], nick+rest)
                mass_privmsg(cli, [guy for guy in badguys 
                    if (guy in var.PLAYERS and
                        var.PLAYERS[guy]["cloak"] in var.SIMPLE_NOTIFY)], nick+rest, True)
            else:
                mass_privmsg(cli, [guy for guy in badguys 
                    if (guy in var.PLAYERS and
                        var.PLAYERS[guy]["cloak"] not in var.SIMPLE_NOTIFY)], "\02{0}\02 zegt: {1}".format(nick, rest))
                mass_privmsg(cli, [guy for guy in badguys 
                    if (guy in var.PLAYERS and
                        var.PLAYERS[guy]["cloak"] in var.SIMPLE_NOTIFY)], "\02{0}\02 zegt: {1}".format(nick, rest), True)



def transition_night(cli):
    if var.PHASE == "nacht":
        return
    var.PHASE = "nacht"

    for x, tmr in var.TIMERS.items():  # cancel daytime timer
        tmr.cancel()
    var.TIMERS = {}

    # Reset nighttime variables
    var.KILLS = {}
    var.GUARDED = {}  # key = by whom, value = the person that is visited
    var.KILLER = ""  # nickname of who chose the victim
    var.SEEN = []  # list of seers that have had visions
    var.OBSERVED = {}  # those whom werecrows have observed
    var.HVISITED = {}
    var.NIGHT_START_TIME = datetime.now()

    daydur_msg = ""

    if var.NIGHT_TIMEDELTA or var.START_WITH_DAY:  #  transition from day
        td = var.NIGHT_START_TIME - var.DAY_START_TIME
        var.DAY_START_TIME = None
        var.DAY_TIMEDELTA += td
        min, sec = td.seconds // 60, td.seconds % 60
        daydur_msg = "Aantal dagen geduurt \u0002{0:0>2}:{1:0>2}\u0002. ".format(min,sec)

    chan = botconfig.CHANNEL

    if var.NIGHT_TIME_LIMIT > 0:
        var.NIGHT_ID = time.time()
        t = threading.Timer(var.NIGHT_TIME_LIMIT, transition_day, [cli, var.NIGHT_ID])
        var.TIMERS["nacht"] = t
        var.TIMERS["nacht"].daemon = True
        t.start()
        
    if var.NIGHT_TIME_WARN > 0:
        t2 = threading.Timer(var.NIGHT_TIME_WARN, night_warn, [cli, var.NIGHT_ID])
        var.TIMERS["night_warn"] = t2
        var.TIMERS["night_warn"].daemon = True
        t2.start()

    # send PMs
    ps = var.list_players()
    wolves = var.ROLES["wolf"]+var.ROLES["verrader"]+var.ROLES["weerkraai"]
    for wolf in wolves:
        normal_notify = wolf in var.PLAYERS and var.PLAYERS[wolf]["cloak"] not in var.SIMPLE_NOTIFY
    
        if normal_notify:
            if wolf in var.ROLES["wolf"]:
                pm(cli, wolf, ('Jij bent een \u0002wolf\u0002. het is aan jou om alle burgers '+
                               'te doden. gebruik "kill <nick>" om een burger te doden.'))
            elif wolf in var.ROLES["verrader"]:
                pm(cli, wolf, ('Jij bent een \u0002verrader\u0002. Je bent net als elke andere '+
                               'burger en zelfs een ziener kan jij ware identiteit zien. '+
                               'Alleen rechercheurs kan. '))
            else:
                pm(cli, wolf, ('Je bent een \u0002c\u0002. In de nacht kun je vliegen. '+
                               'Gebruik "kill <nick>" om een burger te doden. Daarnaast, kun '+
                               'je "observe <nick>" gebruiken om te zien of iemand in bed is of niet. '+
                               'Observeren (observe) be schermt je tegen deelname bij het doden.'))
            if len(wolves) > 1:
                pm(cli, wolf, 'Oh ja, Als je mij een prive bericht stuurd, stuur ik die door naar de wolven.')
        else:
            pm(cli, wolf, "Jij bent een \02{0}\02.".format(var.get_role(wolf)))  # !simple
            
        
        pl = ps[:]
        pl.sort(key=lambda x: x.lower())
        pl.remove(wolf)  # remove self from list
        for i, player in enumerate(pl):
            if player in var.ROLES["wolf"]:
                pl[i] = player + " (wolf)"
            elif player in var.ROLES["verrader"]:
                pl[i] = player + " (verrader)"
            elif player in var.ROLES["weerkraai"]:
                pl[i] = player + " (weerkraai)"
        pm(cli, wolf, "\u0002Spelers:\u0002 "+", ".join(pl))

    for seer in var.ROLES["ziener"]:
        pl = ps[:]
        pl.sort(key=lambda x: x.lower())
        pl.remove(seer)  # remove self from list
        
        if seer in var.PLAYERS and var.PLAYERS[seer]["cloak"] not in var.SIMPLE_NOTIFY:
            pm(cli, seer, ('Jij bent een \u0002ziener\u0002. '+
                          'Het is je werk om de wolf te vinden, je '+
                          'kan één visioen per nacht hebben. '+
                          'Gebruik "see <nick>" om de rol van een speler te zien.'))
        else:
            pm(cli, seer, "Je bent een \02ziener\02.")  # !simple
        pm(cli, seer, "Spelers: "+", ".join(pl))

    for harlot in var.ROLES["onschuldige meisje"]:
        pl = ps[:]
        pl.sort(key=lambda x: x.lower())
        pl.remove(harlot)
        if harlot in var.PLAYERS and var.PLAYERS[harlot]["cloak"] not in var.SIMPLE_NOTIFY:
            cli.msg(harlot, ('Je bent een \u0002onschuldige meisje\u0002. '+
                             'Je brengt de nacht door met één persoon per ronde. '+
                             'Als je een slachtoffer van een wolf of een wolf bezoekt, '+
                             'wordt je gedood. Gebruik "visit <nick>" om een speler te bezoeken.'))
        else:
            cli.notice(harlot, "Jij bent een \02onschuldige meisje\02.")  # !simple
        pm(cli, harlot, "Spelers: "+", ".join(pl))

    for g_angel in var.ROLES["bescherm engel"]:
        pl = ps[:]
        pl.sort(key=lambda x: x.lower())
        pl.remove(g_angel)
        if g_angel in var.PLAYERS and var.PLAYERS[g_angel]["cloak"] not in var.SIMPLE_NOTIFY:
            cli.msg(g_angel, ('Jij bent een \u0002bescherm engel\u0002. '+
                              'Het is je werk om burgers te beschermen. Als je een wolf '+
                              'beschermd, is er een 50/50 kans dat je overlijdt, als je een slachtoffer '+
                              'beschermd, blijven ze leven. Gebruik "guard <nick>" om een speler te beschermen.'))
        else:
            cli.notice(g_angel, "Je bent een \02bescherm engel\02.")  # !simple
        pm(cli, g_angel, "Spelers: " + ", ".join(pl))
    
    for dttv in var.ROLES["rechercheur"]:
        pl = ps[:]
        pl.sort(key=lambda x: x.lower())
        pl.remove(dttv)
        if dttv in var.PLAYERS and var.PLAYERS[dttv]["cloak"] not in var.SIMPLE_NOTIFY:
            cli.msg(dttv, ("Jij bent een \u0002rechercheur\u0002.\n"+
                          "Je werk is om alle wolven en verraders uit teschakelen. "+
                          "Je voert je werk overdag uit, en je ziet de ware "+
                          "identiteit van alle gebruikers, ook de verraders.\n"+
                          "Maar, elke keer dat je mogelijkheid gebruikt, er is een 2/5 "+
                          "kans dat je identiteit zichtbaar wordt voor de wolven. Dus wees "+
                          "voorzichtig. Gebruik \"{0}id\" om de identiteit te ontdekken van een speler.").format(botconfig.CMD_CHAR))
        else:
            cli.notice(dttv, "Jij bent een \02rechercheur\02.")  # !simple
        pm(cli, dttv, "Spelers: " + ", ".join(pl))
    for d in var.ROLES["dronken burger"]:
        if var.FIRST_NIGHT:
            pm(cli, d, 'Je hebt teveel gedronken! Jij bent een \u0002dronken burger\u0002.')

    for g in tuple(var.GUNNERS.keys()):
        if g not in ps:
            continue
        elif not var.GUNNERS[g]:
            continue
        norm_notify = g in var.PLAYERS and var.PLAYERS[g]["cloak"] not in var.SIMPLE_NOTIFY
        if norm_notify:
            gun_msg =  ("Jij hebt een geweer met zilveren kogels. Je kunt hem alleen "+
                        "overdag gebruiken. Als je op een wolf schiet, hij/zij zal direct sterven, maar schiet "+
                        "je een burger, de burger zal het waarschijnlijk overleven. Je hebt {0}.")
        else:
            gun_msg = ("Je hebt een \02geweer\02 met {0}.")
        if var.GUNNERS[g] == 1:
            gun_msg = gun_msg.format("1 kogel")
        elif var.GUNNERS[g] > 1:
            gun_msg = gun_msg.format(str(var.GUNNERS[g]) + " kogels")
        else:
            continue
        
        pm(cli, g, gun_msg)

    dmsg = (daydur_msg + "Het is nu nacht. Alle spelers "+
                   "controleer je prive bericht voor instructies. "+
                   "Heb je er geen ontvangen, blijf dan rustig zitten, "+
                   "relax, en wacht op de morgen die gaat komen.")
    cli.msg(chan, dmsg)
    var.LOGGER.logMessage(dmsg.replace("\02", ""))
    var.LOGGER.logBare("NIGHT", "BEGIN")

    # cli.msg(chan, "DEBUG: "+str(var.ROLES))
    if not var.ROLES["wolf"]:  # Probably something interesting going on.
        chk_nightdone(cli)
        chk_traitor(cli)



def cgamemode(cli, *args):
    chan = botconfig.CHANNEL
    if var.ORIGINAL_SETTINGS:  # needs reset
        reset_settings()
    
    for arg in args:
        modeargs = arg.split("=", 1)
        
        if len(modeargs) < 2:  # no equal sign in the middle of the arg
            cli.msg(botconfig.CHANNEL, "ongeldige syntaxis.")
            return False
        
        modeargs[0] = modeargs[0].strip()
        if modeargs[0] in var.GAME_MODES.keys():
            md = modeargs.pop(0)
            modeargs[0] = modeargs[0].strip()
            try:
                gm = var.GAME_MODES[md](modeargs[0])
                for attr in dir(gm):
                    val = getattr(gm, attr)
                    if (hasattr(var, attr) and not callable(val)
                                            and not attr.startswith("_")):
                        var.ORIGINAL_SETTINGS[attr] = getattr(var, attr)
                        setattr(var, attr, val)
                return True
            except var.InvalidModeException as e:
                cli.msg(botconfig.CHANNEL, "ongeldige modes: "+str(e))
                return False
        else:
            cli.msg(chan, "Modes \u0002{0}\u0002 niet gevonden.".format(modeargs[0]))


@cmd("start")
def start(cli, nick, chann_, rest):
    """Starts a game of Werewolf"""
    
    chan = botconfig.CHANNEL
    
    villagers = var.list_players()
    pl = villagers[:]

    if var.PHASE == "geen":
        cli.notice(nick, "Er is geen spel bezig.")
        return
    if var.PHASE != "join":
        cli.notice(nick, "Weerwolven is al bezig.")
        return
    if nick not in villagers and nick != chan:
        cli.notice(nick, "Je speelt nu niet mee.")
        return
        
    now = datetime.now()
    var.GAME_START_TIME = now  # Only used for the idler checker
    dur = int((var.CAN_START_TIME - now).total_seconds())
    if dur > 0:
        cli.msg(chan, "Wacht minimaal nog z'n {0} seconden.".format(dur))
        return

    if len(villagers) < 4:
        cli.msg(chan, "{0}: Er zijn vier of meer spelers nodig voor dit spel.".format(nick))
        return

    for pcount in range(len(villagers), 3, -1):
        addroles = var.ROLES_GUIDE.get(pcount)
        if addroles:
            break

    if var.ORIGINAL_SETTINGS:  # Custom settings
        while True:
            wvs = (addroles[var.INDEX_OF_ROLE["wolf"]] +
                  addroles[var.INDEX_OF_ROLE["verrader"]])
            if len(villagers) < (sum(addroles) - addroles[var.INDEX_OF_ROLE["kanonnier"]] -
                    addroles[var.INDEX_OF_ROLE["vervloekte burger"]]):
                cli.msg(chan, "Er zijn te weinig spelers in het "+
                              "spel om de standaard regels te gebruiken.")
            elif not wvs:
                cli.msg(chan, "Er moet minimaal één wolf zijn!")
            elif wvs > (len(villagers) / 2):
                cli.msg(chan, "Er zijn te veel wolven.")
            else:
                break
            reset_settings()
            cli.msg(chan, "De standaard instellingen zijn teruggezet. Start opnieuw.")
            var.PHASE = "join"
            return

            
    if var.ADMIN_TO_PING:
        if "join" in COMMANDS.keys():
            COMMANDS["join"] = [lambda *spam: cli.msg(chan, "Dit commanda is uitgeschakeld door een administrator.")]
        if "start" in COMMANDS.keys():
            COMMANDS["start"] = [lambda *spam: cli.msg(chan, "Dit commanda is uitgeschakeld door een administrator.")]

    var.ROLES = {}
    var.CURSED = []
    var.GUNNERS = {}
    var.WOLF_GUNNERS = {}

    villager_roles = ("kanonnier", "vervloekte burger")
    for i, count in enumerate(addroles):
        role = var.ROLE_INDICES[i]
        if role in villager_roles:
            var.ROLES[role] = [None] * count
            continue # We deal with those later, see below
        selected = random.sample(villagers, count)
        var.ROLES[role] = selected
        for x in selected:
            villagers.remove(x)

    # Now for the villager roles
    # Select cursed (just a villager)
    if var.ROLES["vervloekte burger"]:
        possiblecursed = pl[:]
        for cannotbe in (var.ROLES["wolf"] + var.ROLES["weerkraai"] +
                         var.ROLES["ziener"] + var.ROLES["dronken burger"]):
                                              # traitor can be cursed
            possiblecursed.remove(cannotbe)
        
        var.CURSED = random.sample(possiblecursed, len(var.ROLES["vervloekte burger"]))
    del var.ROLES["vervloekte burger"]
    
    # Select gunner (also a villager)
    if var.ROLES["kanonnier"]:
                   
        possible = pl[:]
        for cannotbe in (var.ROLES["wolf"] + var.ROLES["weerkraai"] +
                         var.ROLES["verrader"]):
            possible.remove(cannotbe)
            
        for csd in var.CURSED:  # cursed cannot be gunner
            if csd in possible:
                possible.remove(csd)
                
        for gnr in random.sample(possible, len(var.ROLES["kanonnier"])):
            if gnr in var.ROLES["dronken burger"]:
                var.GUNNERS[gnr] = (var.DRUNK_SHOTS_MULTIPLIER * 
                                    math.ceil(var.SHOTS_MULTIPLIER * len(pl)))
            else:
                var.GUNNERS[gnr] = math.ceil(var.SHOTS_MULTIPLIER * len(pl))
    del var.ROLES["kanonnier"]

    var.ROLES["burger"] = villagers

    cli.msg(chan, ("{0}: Welkom bij Weerwolven van Wakkerdam.").format(", ".join(pl)))
    cli.mode(chan, "+m")

    var.ORIGINAL_ROLES = copy.deepcopy(var.ROLES)  # Make a copy
    
    var.DAY_TIMEDELTA = timedelta(0)
    var.NIGHT_TIMEDELTA = timedelta(0)
    var.DAY_START_TIME = None
    var.NIGHT_START_TIME = None
    
    var.LOGGER.log("Spel Start")
    var.LOGGER.logBare("GAME", "BEGIN", nick)
    var.LOGGER.logBare(str(len(pl)), "PLAYERCOUNT")
    
    var.LOGGER.log("***")
    var.LOGGER.log("ROLES: ")
    for rol in var.ROLES:
        r = []
        for rw in var.plural(rol).split(" "):
            rwu = rw[0].upper()
            if len(rw) > 1:
                rwu += rw[1:]
            r.append(rwu)
        r = " ".join(r)
        var.LOGGER.log("{0}: {1}".format(r, ", ".join(var.ROLES[rol])))
        
        for plr in var.ROLES[rol]:
            var.LOGGER.logBare(plr, "ROLE", rol)
    
    if var.CURSED:
        var.LOGGER.log("Vervloekten: "+", ".join(var.CURSED))
        
        for plr in var.CURSED:
            var.LOGGER.logBare(plr+" ROLE vevloekte burger")
    if var.GUNNERS:
        var.LOGGER.log("Burgers met kogels: "+", ".join([x+"("+str(y)+")" for x,y in var.GUNNERS.items()]))
        for plr in var.GUNNERS:
            var.LOGGER.logBare(plr, "ROLE kanonnier")
    
    var.LOGGER.log("***")        
        
    var.PLAYERS = {plr:dict(var.USERS[plr]) for plr in pl if plr in var.USERS}    

    if not var.START_WITH_DAY:
        var.FIRST_NIGHT = True
        transition_night(cli)
    else:
        transition_day(cli)

    # DEATH TO IDLERS!
    reapertimer = threading.Thread(None, reaper, args=(cli,var.GAME_ID))
    reapertimer.daemon = True
    reapertimer.start()

    
    
@hook("error")
def on_error(cli, pfx, msg):
    if msg.endswith("(Excess Flood)"):
        restart_program(cli, "excess flood", "")
    elif msg.startswith("Closing Link:"):
        raise SystemExit
    


@cmd("wacht")
def wait(cli, nick, chann_, rest):
    """Increase the wait time (before !start can be used)"""
    pl = var.list_players()
    
    chan = botconfig.CHANNEL
    
    
    if var.PHASE == "geen":
        cli.notice(nick, "Er is geen spel bezig.")
        return
    if var.PHASE != "join":
        cli.notice(nick, "Werewolf is already in play.")
        return
    if nick not in pl:
        cli.notice(nick, "Je speelt nu niet mee.")
        return
    if var.WAITED >= var.MAXIMUM_WAITED:
        cli.msg(chan, "Het maximale aantal keren voor het uitbreiden van de wacht tijd is bereikt.")
        return

    now = datetime.now()
    if now > var.CAN_START_TIME:
        var.CAN_START_TIME = now + timedelta(seconds=var.EXTRA_WAIT)
    else:
        var.CAN_START_TIME += timedelta(seconds=var.EXTRA_WAIT)
    var.WAITED += 1
    cli.msg(chan, ("\u0002{0}\u0002 heeft de wachttijd verlengt met "+
                  "{1} seconden.").format(nick, var.EXTRA_WAIT))



@cmd("fwait", admin_only=True)
def fwait(cli, nick, chann_, rest):

    pl = var.list_players()
    
    chan = botconfig.CHANNEL
    
    
    if var.PHASE == "geen":
        cli.notice(nick, "Er is geen spel bezig.")
        return
    if var.PHASE != "join":
        cli.notice(nick, "Weerwolven is al bezig.")
        return

    rest = re.split(" +", rest.strip(), 1)[0]
    if rest and rest.isdigit():
        if len(rest) < 4:
            extra = int(rest)
        else:
            cli.msg(chan, "{0}: We hebben niet de hele dag!".format(nick))
            return
    else:
        extra = var.EXTRA_WAIT
        
    now = datetime.now()
    if now > var.CAN_START_TIME:
        var.CAN_START_TIME = now + timedelta(seconds=extra)
    else:
        var.CAN_START_TIME += timedelta(seconds=extra)
    var.WAITED += 1
    cli.msg(chan, ("\u0002{0}\u0002 heeft de wachttijd geforceerd verlengt met "+
                  "{1} seconden.").format(nick, extra))


@cmd("fstop",admin_only=True)
def reset_game(cli, nick, chan, rest):
    if var.PHASE == "geen":
        cli.notice(nick, "Er is geen spel bezig.")
        return
    cli.msg(botconfig.CHANNEL, "\u0002{0}\u0002 heeft het spel geforceerd gestopt.".format(nick))
    var.LOGGER.logMessage("{0} heeft het spel geforceerd gestopt.".format(nick))
    if var.PHASE != "join":
        stop_game(cli)
    else:
        reset(cli)


@pmcmd("rules")
def pm_rules(cli, nick, rest):
    cli.notice(nick, var.RULES)

@cmd("rules")
def show_rules(cli, nick, chan, rest):
    """Displays the rules"""
    if var.PHASE in ("dag", "nacht") and nick not in var.list_players():
        cli.notice(nick, var.RULES)
        return
    cli.msg(botconfig.CHANNEL, var.RULES)
    var.LOGGER.logMessage(var.RULES)


@pmcmd("help", raw_nick = True)
def get_help(cli, rnick, rest):
    """Gets help."""
    nick, mode, user, cloak = parse_nick(rnick)
    fns = []

    rest = rest.strip().replace(botconfig.CMD_CHAR, "", 1).lower()
    splitted = re.split(" +", rest, 1)
    cname = splitted.pop(0)
    rest = splitted[0] if splitted else ""
    found = False
    if cname:
        for c in (COMMANDS,PM_COMMANDS):
            if cname in c.keys():
                found = True
                for fn in c[cname]:
                    if fn.__doc__:
                        if callable(fn.__doc__):
                            pm(cli, nick, botconfig.CMD_CHAR+cname+": "+fn.__doc__(rest))
                            if nick == botconfig.CHANNEL:
                                var.LOGGER.logMessage(botconfig.CMD_CHAR+cname+": "+fn.__doc__(rest))
                        else:
                            pm(cli, nick, botconfig.CMD_CHAR+cname+": "+fn.__doc__)
                            if nick == botconfig.CHANNEL:
                                var.LOGGER.logMessage(botconfig.CMD_CHAR+cname+": "+fn.__doc__)
                        return
                    else:
                        continue
                else:
                    continue
        else:
            if not found:
                pm(cli, nick, "Commando niet gevonden.")
            else:
                pm(cli, nick, "Er is geen hulp bij dit commando beschikbaar.")
            return
    # if command was not found, or if no command was given:
    for name, fn in COMMANDS.items():
        if (name and not fn[0].admin_only and 
            not fn[0].owner_only and name not in fn[0].aliases):
            fns.append("\u0002"+name+"\u0002")
    afns = []
    if is_admin(cloak) or cloak in botconfig.OWNERS: # todo - is_owner
        for name, fn in COMMANDS.items():
            if fn[0].admin_only and name not in fn[0].aliases:
                afns.append("\u0002"+name+"\u0002")
    cli.notice(nick, "Commands: "+", ".join(fns))
    if afns:
        cli.notice(nick, "Admin Commands: "+", ".join(afns))



@cmd("help", raw_nick = True)
def help2(cli, nick, chan, rest):
    """Gets help"""
    if rest.strip():  # command was given
        get_help(cli, chan, rest)
    else:
        get_help(cli, nick, rest)


@hook("invite", raw_nick = False, admin_only = True)
def on_invite(cli, nick, something, chan):
    if chan == botconfig.CHANNEL:
        cli.join(chan)

      
def is_admin(cloak):
    return bool([ptn for ptn in botconfig.OWNERS+botconfig.ADMINS if fnmatch.fnmatch(cloak.lower(), ptn.lower())])


@cmd("admins")
def show_admins(cli, nick, chan, rest):
    """Pings the admins that are available."""
    admins = []
    pl = var.list_players()
    
    if (var.LAST_ADMINS and
        var.LAST_ADMINS + timedelta(seconds=var.ADMINS_RATE_LIMIT) > datetime.now()):
        cli.notice(nick, ("Dit commando heeft een gebruikerslimiet. " +
                          "Wacht even voor je hem weer gebruikt."))
        return
        
    if not (var.PHASE in ("dag", "nacht") and nick not in pl):
        var.LAST_ADMINS = datetime.now()
    
    if var.ADMIN_PINGING:
        return
    var.ADMIN_PINGING = True

    @hook("whoreply", hookid = 4)
    def on_whoreply(cli, server, dunno, chan, dunno1,
                    cloak, dunno3, user, status, dunno4):
        if not var.ADMIN_PINGING:
            return
        if (is_admin(cloak) and 'G' not in status and
            user != botconfig.NICK and cloak not in var.AWAY):
            admins.append(user)

    @hook("endofwho", hookid = 4)
    def show(*args):
        if not var.ADMIN_PINGING:
            return
        admins.sort(key=lambda x: x.lower())
        
        if var.PHASE in ("dag", "nacht") and nick not in pl:
            cli.notice(nick, "Beschikbare admins: "+" ".join(admins))
        else:
            cli.msg(chan, "Beschikbare admins: "+" ".join(admins))

        decorators.unhook(HOOKS, 4)
        var.ADMIN_PINGING = False

    cli.who(chan)



@cmd("coin")
def coin(cli, nick, chan, rest):
    """It's a bad idea to base any decisions on this command."""
    
    if var.PHASE in ("dag", "nacht") and nick not in var.list_players():
        cli.notice(nick, "Je kunt dit commando nu niet gebruiken.")
        return
    
    cli.msg(chan, "\2{0}\2 gooit een munt in de lucht...".format(nick))
    var.LOGGER.logMessage("{0} gooit een munt in de lucht...".format(nick))
    cmsg = "De munt land op \2{0}\2.".format("kop" if random.random() < 0.5 else "munt")
    cli.msg(chan, cmsg)
    var.LOGGER.logMessage(cmsg)
    


def aftergame(cli, rawnick, rest):
    """Schedule a command to be run after the game by someone."""
    chan = botconfig.CHANNEL
    nick = parse_nick(rawnick)[0]
    
    rst = re.split(" +", rest)
    cmd = rst.pop(0).lower().replace(botconfig.CMD_CHAR, "", 1).strip()

    if cmd in PM_COMMANDS.keys():
        def do_action():
            for fn in PM_COMMANDS[cmd]:
                fn(cli, rawnick, " ".join(rst))
    elif cmd in COMMANDS.keys():
        def do_action():
            for fn in COMMANDS[cmd]:
                fn(cli, rawnick, botconfig.CHANNEL, " ".join(rst))
    else:
        cli.notice(nick, "Dit commando is niet gevonden.")
        return
        
    if var.PHASE == "geen":
        do_action()
        return
    
    cli.msg(chan, ("Het commando \02{0}\02 is ingeplanned om uitgevoerd te worden "+
                  "na dit spel door \02{1}\02.").format(cmd, nick))
    var.AFTER_FLASTGAME = do_action

    

@cmd("faftergame", admin_only=True, raw_nick=True)
def _faftergame(cli, nick, chan, rest):
    if not rest.strip():
        cli.notice(parse_nick(nick)[0], "Onjuiste syntax  voor dit commando.")
        return
    aftergame(cli, nick, rest)
        
    
    
@pmcmd("faftergame", admin_only=True, raw_nick=True)
def faftergame(cli, nick, rest):
    _faftergame(cli, nick, botconfig.CHANNEL, rest)
    
    
@pmcmd("flastgame", admin_only=True, raw_nick=True)
def flastgame(cli, nick, rest):
    """This command may be used in the channel or in a PM, and it disables starting or joining a game. !flastgame <optional-command-after-game-ends>"""
    rawnick = nick
    nick, _, __, cloak = parse_nick(rawnick)
    
    chan = botconfig.CHANNEL
    if var.PHASE != "join":
        if "join" in COMMANDS.keys():
            COMMANDS["join"] = [lambda *spam: cli.msg(chan, "Dit commanda is uitgeschakeld door een administrator.")]
        if "start" in COMMANDS.keys():
            COMMANDS["start"] = [lambda *spam: cli.msg(chan, "Dit commanda is uitgeschakeld door een administrator.")]
        
    cli.msg(chan, "Een nieuw spel starten is uitgeschakeld door \02{0}\02.".format(nick))
    var.ADMIN_TO_PING = nick
    
    if rest.strip():
        aftergame(cli, rawnick, rest)
    
    
    
    
@cmd("flastgame", admin_only=True, raw_nick=True)
def _flastgame(cli, nick, chan, rest):
    flastgame(cli, nick, rest)
    
before_debug_mode_commands = list(COMMANDS.keys())
before_debug_mode_pmcommands = list(PM_COMMANDS.keys())

if botconfig.DEBUG_MODE or botconfig.ALLOWED_NORMAL_MODE_COMMANDS:

    @cmd("eval", owner_only = True)
    @pmcmd("eval", owner_only = True)
    def pyeval(cli, nick, *rest):
        rest = list(rest)
        if len(rest) == 2:
            chan = rest.pop(0)
        else:
            chan = nick
        try:
            a = str(eval(rest[0]))
            if len(a) < 500:
                cli.msg(chan, a)
            else:
                cli.msg(chan, a[0:500])
        except Exception as e:
            cli.msg(chan, str(type(e))+":"+str(e))
            
            
    
    @cmd("exec", owner_only = True)
    @pmcmd("exec", owner_only = True)
    def py(cli, nick, *rest):
        rest = list(rest)
        if len(rest) == 2:
            chan = rest.pop(0)
        else:
            chan = nick
        try:
            exec(rest[0])
        except Exception as e:
            cli.msg(chan, str(type(e))+":"+str(e))

            

    @cmd("revealroles", admin_only=True)
    def revroles(cli, nick, chan, rest):
        if var.PHASE != "geen":
            cli.msg(chan, str(var.ROLES))
        if var.PHASE in ('nacht','dag'):
            cli.msg(chan, "Vervloekt: "+str(var.CURSED))
            cli.msg(chan, "Kanonnier: "+str(list(var.GUNNERS.keys())))
        
        
    @cmd("fgame", admin_only=True)
    def game(cli, nick, chan, rest):
        pl = var.list_players()
        if var.PHASE == "geen":
            cli.notice(nick, "Er is geen spel bezig.")
            return
        if var.PHASE != "join":
            cli.notice(nick, "Weerwolven is al bezig.")
            return
        if nick not in pl:
            cli.notice(nick, "Jij speelt nu niet mee.")
            return
        rest = rest.strip().lower()
        if rest:
            if cgamemode(cli, *re.split(" +",rest)):
                cli.msg(chan, ("\u0002{0}\u0002 heeft de spel "+
                                "instellingen succesvol aangepast.").format(nick))
    
    def fgame_help(args = ""):
        args = args.strip()
        if not args:
            return "Available game mode setters: "+ ", ".join(var.GAME_MODES.keys())
        elif args in var.GAME_MODES.keys():
            return var.GAME_MODES[args].__doc__
        else:
            return "Game mode setter {0} not found.".format(args)

    game.__doc__ = fgame_help


    # DO NOT MAKE THIS A PMCOMMAND ALSO
    @cmd("force", admin_only=True)
    def forcepm(cli, nick, chan, rest):
        rst = re.split(" +",rest)
        if len(rst) < 2:
            cli.msg(chan, "De syntax is incorrect.")
            return
        who = rst.pop(0).strip()
        if not who or who == botconfig.NICK:
            cli.msg(chan, "Dat werkt niet.")
            return
        if not is_fake_nick(who):
            ul = list(var.USERS.keys())
            ull = [u.lower() for u in ul]
            if who.lower() not in ull:
                cli.msg(chan, "Dit kan alleen gedaan worden op niet bestaande nicknames.")
                return
            else:
                who = ul[ull.index(who.lower())]
        cmd = rst.pop(0).lower().replace(botconfig.CMD_CHAR, "", 1)
        did = False
        if PM_COMMANDS.get(cmd) and not PM_COMMANDS[cmd][0].owner_only:
            if (PM_COMMANDS[cmd][0].admin_only and nick in var.USERS and 
                not is_admin(var.USERS[nick]["cloak"])):
                # Not a full admin
                cli.notice(nick, "Only full admins can force an admin-only command.")
                return
                
            for fn in PM_COMMANDS[cmd]:
                if fn.raw_nick:
                    continue
                fn(cli, who, " ".join(rst))
                did = True
            if did:
                cli.msg(chan, "Operation successful.")
            else:
                cli.msg(chan, "Not possible with this command.")
            #if var.PHASE == "night":   <-  Causes problems with night starting twice.
            #    chk_nightdone(cli)
        elif COMMANDS.get(cmd) and not COMMANDS[cmd][0].owner_only:
            if (COMMANDS[cmd][0].admin_only and nick in var.USERS and 
                not is_admin(var.USERS[nick]["cloak"])):
                # Not a full admin
                cli.notice(nick, "Only full admins can force an admin-only command.")
                return
                
            for fn in COMMANDS[cmd]:
                if fn.raw_nick:
                    continue
                fn(cli, who, chan, " ".join(rst))
                did = True
            if did:
                cli.msg(chan, "Operation successful.")
            else:
                cli.msg(chan, "Not possible with this command.")
        else:
            cli.msg(chan, "That command was not found.")
            
            
    @cmd("rforce", admin_only=True)
    def rforcepm(cli, nick, chan, rest):
        rst = re.split(" +",rest)
        if len(rst) < 2:
            cli.msg(chan, "The syntax is incorrect.")
            return
        who = rst.pop(0).strip().lower()
        who = who.replace("_", " ")
        
        if (who not in var.ROLES or not var.ROLES[who]) and (who != "gunner"
            or var.PHASE in ("geen", "join")):
            cli.msg(chan, nick+": invalid role")
            return
        elif who == "gunner":
            tgt = list(var.GUNNERS.keys())
        else:
            tgt = var.ROLES[who]

        cmd = rst.pop(0).lower().replace(botconfig.CMD_CHAR, "", 1)
        if PM_COMMANDS.get(cmd) and not PM_COMMANDS[cmd][0].owner_only:
            if (PM_COMMANDS[cmd][0].admin_only and nick in var.USERS and 
                not is_admin(var.USERS[nick]["cloak"])):
                # Not a full admin
                cli.notice(nick, "Only full admins can force an admin-only command.")
                return
        
            for fn in PM_COMMANDS[cmd]:
                for guy in tgt[:]:
                    fn(cli, guy, " ".join(rst))
            cli.msg(chan, "Operation successful.")
            #if var.PHASE == "night":   <-  Causes problems with night starting twice.
            #    chk_nightdone(cli)
        elif cmd.lower() in COMMANDS.keys() and not COMMANDS[cmd][0].owner_only:
            if (COMMANDS[cmd][0].admin_only and nick in var.USERS and 
                not is_admin(var.USERS[nick]["cloak"])):
                # Not a full admin
                cli.notice(nick, "Only full admins can force an admin-only command.")
                return
        
            for fn in COMMANDS[cmd]:
                for guy in tgt[:]:
                    fn(cli, guy, chan, " ".join(rst))
            cli.msg(chan, "Operation successful.")
        else:
            cli.msg(chan, "That command was not found.")



    @cmd("frole", admin_only=True)
    def frole(cli, nick, chan, rest):
        rst = re.split(" +",rest)
        if len(rst) < 2:
            cli.msg(chan, "The syntax is incorrect.")
            return
        who = rst.pop(0).strip()
        rol = " ".join(rst).strip()
        ul = list(var.USERS.keys())
        ull = [u.lower() for u in ul]
        if who.lower() not in ull:
            if not is_fake_nick(who):
                cli.msg(chan, "Could not be done.")
                cli.msg(chan, "The target needs to be in this channel or a fake name.")
                return
        if not is_fake_nick(who):
            who = ul[ull.index(who.lower())]
        if who == botconfig.NICK or not who:
            cli.msg(chan, "No.")
            return
        if rol not in var.ROLES.keys():
            pl = var.list_players()
            if var.PHASE not in ("night", "day"):
                cli.msg(chan, "This is only allowed in game.")
                return
            if rol.startswith("gunner"):
                rolargs = re.split(" +",rol, 1)
                if len(rolargs) == 2 and rolargs[1].isdigit():
                    if len(rolargs[1]) < 7:
                        var.GUNNERS[who] = int(rolargs[1])
                        var.WOLF_GUNNERS[who] = int(rolargs[1])
                    else:
                        var.GUNNERS[who] = 999
                        var.WOLF_GUNNERS[who] = 999
                else:
                    var.GUNNERS[who] = math.ceil(var.SHOTS_MULTIPLIER * len(pl))
                if who not in pl:
                    var.ROLES["villager"].append(who)
            elif rol == "cursed villager":
                if who not in var.CURSED:
                    var.CURSED.append(who)
                if who not in pl:
                    var.ROLES["villager"].append(who)
            else:
                cli.msg(chan, "Not a valid role.")
                return
            cli.msg(chan, "Operation successful.")
            return
        if who in var.list_players():
            var.del_player(who)
        var.ROLES[rol].append(who)
        cli.msg(chan, "Operation successful.")
        if var.PHASE not in ('geen','join'):
            chk_win(cli)
            
if botconfig.ALLOWED_NORMAL_MODE_COMMANDS and not botconfig.DEBUG_MODE:
    for comd in list(COMMANDS.keys()):
        if (comd not in before_debug_mode_commands and 
            comd not in botconfig.ALLOWED_NORMAL_MODE_COMMANDS):
            del COMMANDS[comd]
    for pmcomd in list(PM_COMMANDS.keys()):
        if (pmcomd not in before_debug_mode_pmcommands and
            pmcomd not in botconfig.ALLOWED_NORMAL_MODE_COMMANDS):
            del PM_COMMANDS[pmcomd]
