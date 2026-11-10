import random

SHAPES = ["CIRCLE", "TRIANGLE", "CROSS", "SQUARE"]

SYMBOLS = {
    "CIRCLE": "●",
    "TRIANGLE": "▲",
    "CROSS": "✚",
    "SQUARE": "■"
}

STAKES = {
    50: 85,
    100: 180,
    200: 350,
    300: 500,
    500: 900,
    1000: 1900
}

NAMES = [
    # Hausa
    "Musa", "Aisha", "Sani", "Zainab", "Ibrahim", "Hadiza",
    "Usman", "Fatima", "Bello", "Maryam", "Yusuf", "Hauwa",
    "Abubakar", "Rukayya", "Aminu", "Safiya",

    # Yoruba
    "Ade", "Tunde", "Kunle", "Bola", "Yetunde", "Damilola",
    "Adebayo", "Funke", "Wale", "Toyin", "Segun", "Bisola",
    "Femi", "Ronke", "Seyi", "Kemi",

    # Igbo
    "Chinedu", "Nneka", "Emeka", "Adaeze", "Kelechi", "Ifeoma",
    "Obinna", "Chiamaka", "Uche", "Ngozi", "Chukwuemeka", "Amaka",
    "Somto", "Tochukwu", "Oluchi", "Ebuka",

    # Nigerian and English names
    "Daniel", "Grace", "Victor", "Olivia", "James", "Esther",
    "Malik", "Zara", "Samuel", "Sophia", "David", "Amara",
    "Michael", "Jessica", "Benjamin", "Victoria", "Alex", "Faith",

    # Gaming-style names
    "Shadow", "Champion", "KingAce", "LuckyStar", "NightWolf",
    "FireKing", "Diamond", "Thunder", "SilentKiller", "AceMaster",
    "DarkKnight", "GoldenBoy", "QueenBee", "Storm", "Legend",
    "RoyalAce", "FastHands", "WhotKing", "WhotQueen", "BossPlayer"
]


def make_deck():
    deck = []

    for shape in SHAPES:
        for number in range(1, 13):
            deck.append({"shape": shape, "number": number})

    deck += [
        {"shape": "CIRCLE", "number": 13},
        {"shape": "TRIANGLE", "number": 13},
        {"shape": "CROSS", "number": 14},
        {"shape": "SQUARE", "number": 14}
    ]

    random.shuffle(deck)
    return deck


def playable(card, top, active_shape):
    return (
        card["shape"] == active_shape
        or card["number"] == top["number"]
    )


def choose_shape(hand):
    counts = {shape: 0 for shape in SHAPES}

    for card in hand:
        if card["shape"] in counts:
            counts[card["shape"]] += 1

    return max(counts, key=counts.get)


def draw_cards(game, hand, amount):
    for _ in range(amount):
        if not game["deck"] and len(game["discard"]) > 1:
            top = game["discard"].pop()
            game["deck"] = game["discard"]
            game["discard"] = [top]
            random.shuffle(game["deck"])

        if game["deck"]:
            hand.append(game["deck"].pop())


def start_game(stake):
    deck = make_deck()

    player = [deck.pop() for _ in range(5)]
    bot = [deck.pop() for _ in range(5)]
    first = deck.pop()

    return {
        "stake": stake,
        "ai_level": "powerful" if stake >= 300 else "normal",
        "prize": STAKES[stake],
        "deck": deck,
        "discard": [first],
        "player": player,
        "bot": bot,
        "bot_name": random.choice(NAMES),
        "active_shape": first["shape"],
        "extra_turn": False,
        "finished": None,
        "message": "Your turn. Play a matching card."
    }


def bot_move(game):
    bot = game["bot"]
    powerful = game.get("ai_level") == "powerful"

    while bot:
        top = game["discard"][-1]

        choices = [
            (i, card) for i, card in enumerate(bot)
            if playable(card, top, game["active_shape"])
        ]

        if not choices:
            draw_cards(game, bot, 1)
            game["message"] = game["bot_name"] + " picked a card. Your turn."
            return

        def score(item):
            index, card = item
            remaining = bot[:index] + bot[index + 1:]

            counts = {shape: 0 for shape in SHAPES}
            for held in remaining:
                counts[held["shape"]] += 1

            strongest_shape = max(counts.values()) if counts else 0
            shape_score = counts[card["shape"]]

            special = card["number"] in [1, 2, 8, 14]
            player_cards = len(game["player"])

            if powerful:
                value = shape_score * 5

                if special:
                    value += 3

                if card["number"] == 2 and player_cards <= 4:
                    value += 12

                if card["number"] == 14 and player_cards <= 3:
                    value += 10

                if card["number"] in [1, 8]:
                    value += 5

                if shape_score == strongest_shape and strongest_shape:
                    value += 4

                return value + random.random() * 0.5

            else:
                value = shape_score * 2

                if special:
                    value += 2

                if card["number"] == 2 and player_cards <= 3:
                    value += 5

                if card["number"] == 14 and player_cards <= 2:
                    value += 4

                return value + random.random() * 5

        index, card = max(choices, key=score)

        bot.pop(index)
        game["discard"].append(card)
        game["active_shape"] = card["shape"]

        if not bot:
            game["message"] = game["bot_name"] + " played its last card."
            return

        if card["number"] == 2:
            draw_cards(game, game["player"], 2)
            game["message"] = game["bot_name"] + " played 2. You picked 2 cards."
            continue

        if card["number"] == 14:
            draw_cards(game, game["player"], 1)
            game["message"] = game["bot_name"] + " played 14. You picked 1 card."
            continue

        if card["number"] in [8, 1]:
            game["message"] = game["bot_name"] + " played " + str(card["number"]) + ". Opponent continues."
            continue

        game["message"] = game["bot_name"] + " played a card. Your turn."
        return


def player_play(game, index, selected_shape=None):
    hand = game["player"]

    if index < 0 or index >= len(hand):
        return False, "Invalid card."

    card = hand[index]
    top = game["discard"][-1]

    if not playable(card, top, game["active_shape"]):
        return False, "That card cannot be played."

    hand.pop(index)
    game["discard"].append(card)
    game["active_shape"] = card["shape"]

    if not hand:
        return True, "WIN"

    number = card["number"]

    if number == 2:
        draw_cards(game, game["bot"], 2)
        game["extra_turn"] = True
        game["message"] = "You played 2. Opponent picked 2 cards. Play again!"

    elif number == 14:
        draw_cards(game, game["bot"], 1)
        game["extra_turn"] = True
        game["message"] = "You played 14. Opponent picked 1 card. Play again!"

    elif number == 8:
        game["extra_turn"] = True
        game["message"] = "You played 8. Play again!"

    elif number == 1:
        game["extra_turn"] = True
        game["message"] = "You played 1. Play again!"

    else:
        game["extra_turn"] = False

    if not game["bot"]:
        return True, "LOSE"

    return True, game["message"]
