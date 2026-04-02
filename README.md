Texas Hold'em Preflop Trainer

This is a local, desktop application for macOS designed to help poker players train and improve their preflop decision-making. It provides a clean graphical user interface (GUI) to drill realistic preflop scenarios, get instant feedback against a reference strategy, and track performance over time.

The app runs 100% locally. It does not require an internet connection or any cloud services.

Features

Persistent Statistics: Your training history and scores are now saved permanently in a local poker-trainer.db file.

Pro-Level Scenarios: Generates random scenarios for all key preflop situations:

"Raise First In" (RFI)

"vs. Raise" (e.g., BB vs. BTN Open)

"vs. 3-Bet" (e.g., MP vs. BTN 3-Bet)

"vs. 4-Bet" (e.g., BTN vs. MP 4-Bet)

Smart Training Engine: The app auto-detects all available strategy charts (.json files) and drills you on them.

Training Modes:

Drill Mode: Face a continuous stream of hands from all available charts.

Focus Mode: Target and practice a specific position (e.g., "only play the Button").

Instant Feedback: Compares your action (Fold, Call, Raise) to the loaded strategy.

Coaching Notes: Provides brief explanations for why an action is correct.

Visual Range Matrix: Shows your hand in the context of the entire strategy range.

Performance Tracking: A dedicated statistics page tracks your accuracy over time, broken down by position and stack depth.

Polished UI: Displays hands as visual cards with clear, modern fonts and colors.

Included Strategy Charts

This app is data-driven. This download includes a 100BB 6-Max package covering all RFI, vs. RFI, vs. 3-Bet, and vs. 4-Bet spots.

(15 Charts Total)

RFI (5 charts): UTG, MP, CO, BTN, SB

vs. RFI (8 charts):

BTN vs (UTG, MP)

SB vs (BTN)

BB vs (UTG, MP, CO, BTN, SB)

vs. 3-Bet (1 chart):

cash_6max_100bb_MP_vs_BTN_3Bet.json

vs. 4-Bet (1 chart):

cash_6max_100bb_BTN_vs_MP_4Bet.json (New)

Requirements

macOS

Python 3.10+

How to Run the App

(Same as before)

1. Navigate to the Project Directory

cd /path/to/poker-trainer-mac


2. Create a Python Virtual Environment

python3 -m venv venv


3. Activate the Virtual Environment

source venv/bin/activate


4. Install Required Libraries

pip install -r requirements.txt


5. Run the Application

python3 main.py


A poker-trainer.db file will be created to store your progress.