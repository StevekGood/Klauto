class TelegramUserDatabase:    
    def __init__(self, user_whitelist, user_blacklist):
        self.users = dict()
        self.user_whitelist = user_whitelist or []
        self.user_blacklist = user_blacklist or []

    def get_user(self, tg_user_id):
        return self.users.get(tg_user_id)

    def register(self, tg_user_id, user_id, auth_key):
        if not tg_user_id or self.get_user(tg_user_id) or tg_user_id in self.user_blacklist or (len(self.user_whitelist) > 0 and tg_user_id not in self.user_whitelist):
            return False

        self.users[tg_user_id] = {
            "user_id": user_id,
            "auth_key": auth_key
        }
        return True