# --------- std/extra libraries
import requests
import time
import os
import urllib
from datetime import datetime, timedelta, time as dtime, date

# -------- project modules
from bot.utils import (
    is_available_command,
    command_takes_input,
    get_hint_message,
    get_command_handler,
    time_in_range,
)
from bot.db import DBHelper
from bot.data_types import Message, User
from loggingconfigs import config_logger

# -------- loggers setup
log = config_logger(__name__)
bot_token = os.environ.get("BOT_TOKEN")
if not bot_token:
    exit("Provide your telegram bot token!")
# base url for our requests to the telegram APIs
URL = f"https://api.telegram.org/bot{bot_token}/"


def get_updates(offset=None):
    """Get updates after the offset"""
    # timeout will keep the pipe open and tell us when there"re new updates
    url = URL + 'getUpdates?timeout=20&allowed_updates=["messages"]'
    if offset:
        url += f"&offset={offset}"  # add offset if exists
        log.debug("update offset: " + str(offset))
    return requests.get(url).json()  # return dict of latest updates


def send_message(chat_id, text):
    """Encodes ``text`` using url-based encoding and send it to ``chat_id``"""
    requests.get(
        URL + f"sendMessage?chat_id={chat_id}&text={urllib.parse.quote_plus(text)}"
    )


def last_update_id(updates):
    """takes dict of updates and return the id of last one"""
    log.info("listing updates to be handled...")
    update_ids = [int(update["update_id"]) for update in updates["result"]]
    return max(update_ids)  # the last update is the higher one


current_command = None  # stores currently operating command


def handle_updates(updates: list, db: DBHelper):
    """Handles incoming updates to the bot"""
    global current_command  # use current_command var from global scope
    for update in updates:  # loop through updates
        # db.add_message((id: int, update_id: int, user_id: int, chat_id: int, date: int(unix_timestamp), text: str))

        # TODO: common message and user data from the same update

        # Skip edited messages
        if not update.get("message"):
            continue

        # getting message data
        msg_id = update.get("message").get("message_id")  # message id
        msg_update_id = update.get("update_id")  # update id of this message
        msg_user_id = update.get("message").get("from").get("id")  # sending user
        msg_chat_id = (
            update.get("message").get("chat").get("id")
        )  # chat id of the message
        msg_date = update.get("message").get("date")  # message date
        msg_text = update.get("message").get("text", "")  # message text

        log.info("collecting message data... done")
        # Create Message object from incoming data
        msg = Message(
            msg_id, msg_update_id, msg_user_id, msg_chat_id, msg_date, msg_text
        )
        log.info("creating message object from collected data... done")
        if not db.get_message(msg.id):  # if message doesn't exist already
            db.add_message(msg)
            log.info("New message saved.")

        # db.add_user((id: int, is_bot: int, is_admin: int, first_name: str, last_name: str,
        # username: str, language_code: str, active: int(0|1), created: int(unix_timestamp),
        # updated: int(unix_timestamp), last_command: str))
        user_id = update.get("message").get("from").get("id")
        user_is_bot = update.get("message").get("from").get("is_bot")
        user_first_name = update.get("message").get("from").get("first_name")
        user_last_name = update.get("message").get("from").get("last_name")
        user_username = update.get("message").get("from").get("username")
        user_language_code = (
            update.get("message").get("from").get("language_code", "en")
        )
        user_created = time.time()
        user_updated = time.time()
        user_last_command = None
        user_chat_id = update.get("message").get("chat").get("id")
        log.info("collecting user data... done")
        # if user doesn't exist, add him/her to db
        if not db.get_user(user_id):
            user_is_admin = False
            user_active = True
            user = User(
                user_id,
                user_is_bot,
                user_is_admin,
                user_first_name,
                user_last_name,
                user_username,
                user_language_code,
                user_active,
                user_created,
                user_updated,
                user_last_command,
                user_chat_id,
            )
            db.add_user(user)
            log.info("New user saved.")

        log.info("Old user..")
        # Create user object from saved data
        user = db.get_user(user_id)
        if not user.chat_id:
            log.info("User does't have a chat_id yet!")
            db.set_user_chat_id(user.id, time.time(), user_chat_id)
            log.info("Updated user's chat_id")
            # get user again after updating chat_id
            user = db.get_user(user_id)
        log.info("creating user object from collected data... done")

        user_last_command = user.last_command
        text = None  # msg text
        chat = msg_chat_id  # chat id
        log.debug("user: " + str(user_id) + " sent a message - chat_id: " + str(chat))
        if msg_text:  # handle text messages only
            text = msg_text.strip()  # extract msg text
            if text and chat:  # make sure we have txt msg and chat_id
                log.info("text message and chat_id are  extracted.")
                if text.startswith("/"):  # if command
                    if is_available_command(text):  # if command is available
                        current_command = text  # set current command
                        log.info('command: "' + current_command + '" is available.')
                        db.set_user_last_command(
                            user.id, time.time(), current_command
                        )  # update user's last command
                        if command_takes_input(
                            current_command
                        ):  # if command operates on inputs
                            hint_message = get_hint_message(
                                current_command
                            )  # get command hint message
                            send_message(
                                chat, hint_message
                            )  # send a help message to receive inputs later
                            log.info("sending hint message to user... done")
                        else:  # if command is available and does not operate on inputs
                            log.info(
                                'command: "' + current_command + '" has no argument.'
                            )
                            # execute command directly
                            if current_command == "/stop":
                                get_command_handler(current_command)(
                                    db, user_id, time.time(), False
                                )
                                current_command = None
                            elif current_command == "/start":
                                get_command_handler(current_command)(
                                    db, user_id, time.time(), True
                                )
                                current_command = None
                            else:
                                send_message(
                                    chat, get_command_handler(current_command)()
                                )
                                # then unset current_command, commands_without_args execute once!
                                current_command = None
                                log.info("updating user current command.. one time cmd")
                                db.set_user_last_command(
                                    user.id, time.time(), current_command
                                )

                    else:  # if command is not available
                        log.info("Undefined Command")
                        send_message(chat, "Use a defined command.")
                else:  # if sent message does not start with a slash
                    log.info(
                        "working on user's last command.. " + str(user.last_command)
                    )
                    last_command = user.last_command
                    if command_takes_input(
                        last_command
                    ):  # should be an argument if current_command is set
                        log.info("received command arguments from user...")
                        send_message(chat, get_command_handler(last_command)(text))
                        log.info("sending message to user... done")
                    elif current_command in ["/start", "/stop"]:
                        continue  # skip
                    else:
                        log.info("Undefined Command.")
                        send_message(chat, "Use a defined command.")
        else:  # if no text message
            log.debug(
                "A non text message is sent by user: "
                + str(user_id)
                + " - chat id: "
                + str(chat)
            )
            send_message(chat, "I handle text messages only!")


def main(db: DBHelper):
    """The entry point"""
    updates_offset = None  # track last_update_id to use it as offset
    while True:  # infinitely listen to new updates (as long as the script is running)
        try:
            # =============================== Handling Schedule ==============================================
            # Order  =     0           1          2            3         4          5          6
            weekdays = (
                "monday",
                "tuesday",
                "wednesday",
                "thursday",
                "friday",
                "saturday",
                "sunday",
            )
            study_days = (5, 6, 0, 1, 2)
            today = datetime.today().weekday()  # What is today?
            now_in_egypt = str(
                format(datetime.utcnow() + timedelta(hours=2), "%H:%M:%S")
            )  # Cairo time = UTC+2
            now_in_egypt = dtime(
                *[int(x) for x in now_in_egypt.split(":")]
            )  # to datetime.time object
            before_eight = dtime(7, 59, 45)  # get before 8:00AM with 5 seconds
            after_eight = dtime(8, 0, 15)  # get after 8:00AM with 5 seconds

            # if it's in range (07:59:55 |08:00| 08:00:05) in the morning
            if (
                time_in_range(before_eight, after_eight, now_in_egypt)
                and today in study_days
            ):
                schedule = db.get_schedule_of(
                    weekdays[today]
                )  # get schedule of today
                # ================== formating the message to send
                msg_schedule_part = ""
                for idx, entry in enumerate(schedule):
                    msg_schedule_part += (
                        str(idx + 1) + ". " + entry[1] + " at " + entry[0] + "\n"
                    )
                msg = (
                    "Good morning, \n"
                    "today is {0} and the schedule is: \n\n"
                    "{1}".format(weekdays[today].title(), msg_schedule_part)
                )
                users = db.get_users()  # get list of all users
                for user in users:
                    if user.active:
                        log.info(f"Sending today's schedule to: {user}")
                        send_message(user.chat_id, msg)  # send today's schedule
                        time.sleep(
                            0.5
                        )  # sleep for .5 second before sending to the next user

            # =============================== Handling Announcements =========================================
            before_seven = dtime(6, 59, 45)  # get before 7:00AM with 5 seconds
            after_seven = dtime(7, 0, 15)  # get after 7:00AM with 5 seconds
            before_seven = dtime(20, 16, 0)  # get before 7:00AM with 5 seconds
            after_seven = dtime(20, 17, 0)  # get after 7:00AM with 5 seconds
            if time_in_range(before_seven, after_seven, now_in_egypt):
                anns = db.get_announcements()
                for ann in anns:
                    if ann.done == "" or ann.done is None:
                        users = db.get_users()  # get list of all users
                        for user in users:
                            if user.active:
                                log.info(
                                    f"Sending announcement: {ann} schedule to: {user}"
                                )
                                send_message(user.chat_id, ann.description)
                                time.sleep(
                                    0.5
                                )  # sleep for .5 second before sending to the next user
                        db.update_announcement(ann.id, "once")
                    elif ann.done == "cancelled":
                        users = db.get_users()  # get list of all users
                        for user in users:
                            if user.active:
                                log.info(
                                    f"Sending cancelled announcement: {ann} schedule to: {user}"
                                )
                                send_message(
                                    user.chat_id, ann.description + " IS CANCELLED"
                                )
                                time.sleep(
                                    0.5
                                )  # sleep for .5 second before sending to the next user
                        db.update_announcement(ann.id, "twice")
                    else:  # if ann.done=="once"
                        list_ann_time = ann.time.split(" ")
                        ann_time_day = int(list_ann_time[0].split("-")[0])
                        ann_time_month = int(list_ann_time[0].split("-")[1])
                        ann_day = date(
                            datetime.today().year, ann_time_month, ann_time_day
                        )
                        today = datetime.today().date()
                        if (ann_day - today).days == 1:
                            for user in users:
                                if user.active:
                                    log.info(
                                        f"Sending announcement (done=once): {ann} schedule to: {user}"
                                    )
                                    send_message(
                                        user.chat_id, ann.description + " TOMORROW"
                                    )
                                    time.sleep(
                                        0.5
                                    )  # sleep for .5 second before sending to the next user
                            db.update_announcement(ann.id, "twice")
            # =============================== Handling incoming messages =====================================
            log.info("getting updates...")
            updates = get_updates(
                updates_offset
            )  # get new updates after last handled one
            if "result" in updates:  # to prevent KeyError exception
                if (
                    len(updates["result"]) > 0
                ):  # make sure updates list is longer than 0
                    updates_offset = (
                        last_update_id(updates) + 1
                    )  # to remove handled updates
                    handle_updates(
                        updates["result"], db
                    )  # handle new (unhandled) updates
                else:
                    log.info("no updates to be handled")

            time.sleep(0.5)  # delay the loop a .5 second
        except KeyboardInterrupt:  # exit on Ctrl-C
            log.info("\nquiting...")
            exit(0)


if __name__ == "__main__":
    # Setting DB
    db = DBHelper()
    db.setup()
    log.info("Running bot...")
    main(db)
