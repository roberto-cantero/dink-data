# Decode events and the score with the rules of pickleball

Detectors for hits, bounces and serves make independent mistakes. We don't trust them one by one. A rally grammar decoder and a score decoder each find the most likely sequence that obeys the rules, using Viterbi, so impossible sequences get corrected without training labels. Real rallies break the textbook, so unusual but legal sequences are allowed with a penalty, and an "unexplained" end exists.
