# Decode events with the rules of pickleball

Detectors for hits, bounces and serves make independent mistakes. We don't trust them one by one. A rally grammar decoder finds the most likely sequence of events inside a rally that obeys the rules, using Viterbi, so impossible sequences get corrected without training labels. Real rallies break the textbook, so unusual but legal sequences are allowed with a penalty, and an "unexplained" end exists. Players often break the serving rules, so the serve sequence across a game is only weak evidence and never a hard rule (ADR 0019).
