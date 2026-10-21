# Read the score from serves, not from the ball

Superseded by ADR 0019. The serves now give a weak, local hint about each rally's winner, and no score is reported.

Under side-out scoring, who serves next, and from which side, reveals who won the previous rally. The score decoder uses the serving player's identity and side at each serve as its main evidence, with the ball-based winner as a weak hint. The score can therefore ship before the ball tracker works. The cost is that telling the two partners apart becomes the riskiest assumption, so the M0 player spike measures partner identity for the near and far team before M2 is designed.
