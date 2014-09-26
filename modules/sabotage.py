# Copyright (c) 2011, Jimmy Cao
# All rights reserved.

# Redistribution and use in source and binary forms, with or without modification, are permitted provided that the following conditions are met:

# Redistributions of source code must retain the above copyright notice, this list of conditions and the following disclaimer.
# Redistributions in binary form must reproduce the above copyright notice, this list of conditions and the following disclaimer in the documentation and/or other materials provided with the distribution.
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.


from tools import decorators
import settings.sabotage as var
import time
from datetime import datetime, timedelta
import botconfig

COMMANDS = {}
PM_COMMANDS = {}
HOOKS = {}

cmd = decorators.generate(COMMANDS)
pmcmd = decorators.generate(PM_COMMANDS)
hook = decorators.generate(HOOKS, raw_nick=True, permissions=False)

def connect_callback(cli):
    var.PHASE = "geen"
    var.PLAYERS = []
    
    var.LAST_STATS = None


@cmd("join")
def join(cli, nick, chan, rest):
    """Either starts a new game of Werewolf or joins an existing game that has not started yet."""
    
    if var.PHASE == "geen":
    
        cli.mode(chan, "+v", nick, nick+"!*@*")
        var.PLAYERS.append(nick)
        var.PHASE = "join"
        var.WAITED = 0
        var.GAME_ID = time.time()
        var.CAN_START_TIME = datetime.now() + timedelta(seconds=var.MINIMUM_WAIT)
        cli.msg(chan, ('\u0002{0}\u0002 Heeft een spel gestart. '+
                      'Tik "{1}join" om mee te spelen. Tik "{1}start" om het spel te starten. '+
                      'Tik "{1}wait" om nog even te wachten met het staten van het spel.').format(nick, botconfig.CMD_CHAR))
    elif nick in var.PLAYERS:
        cli.notice(nick, "Je speelt al mee!")
    elif len(pl) >= var.MAX_PLAYERS:
        cli.notice(nick, "Het spel zit al vol. Probeer het later nog eens.")
    elif var.PHASE != "join":
        cli.notice(nick, "Sorry het spel is al bezig. Probeer het later nog eens.")
    else:
    
        cli.mode(chan, "+v", nick, nick+"!*@*")
        var.PLAYERS.append(nick)
        cli.msg(chan, '\u0002{0}\u0002 doet mee met het spel.'.format(nick))
        
        var.LAST_STATS = None # reset
