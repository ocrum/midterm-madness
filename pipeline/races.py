"""Race list and scoring rules, transcribed from the Midterm Madness 2026 sheet.

Cook ratings are frozen on the sheet (Senate Sept 23, House Sept 25, 2026), so they
are data here, not something fetched.
"""

STATE_NAMES = {
    'AK': 'alaska', 'AZ': 'arizona', 'CA': 'california', 'CO': 'colorado', 'FL': 'florida',
    'GA': 'georgia', 'IA': 'iowa', 'KS': 'kansas', 'ME': 'maine', 'MI': 'michigan',
    'MN': 'minnesota', 'MT': 'montana', 'NC': 'north-carolina', 'NE': 'nebraska',
    'NH': 'new-hampshire', 'NJ': 'new-jersey', 'NM': 'new-mexico', 'NV': 'nevada',
    'NY': 'new-york', 'OH': 'ohio', 'PA': 'pennsylvania', 'SC': 'south-carolina',
    'TX': 'texas', 'VA': 'virginia', 'WA': 'washington', 'WI': 'wisconsin',
}

# (sheet #, state, Cook rating, Dem-side candidate, party letter, GOP candidate, special election?)
SENATE = [
    (1, 'GA', 'LkD', 'Jon Ossoff', 'D', 'Mike Collins', False),
    (2, 'NC', 'LnD', 'Roy Cooper', 'D', 'Michael Whatley', False),
    (3, 'AK', 'T', 'Mary Peltola', 'D', 'Dan Sullivan', False),
    (4, 'IA', 'T', 'Josh Turek', 'D', 'Ashley Hinson', False),
    (5, 'ME', 'T', 'Troy Jackson', 'D', 'Susan Collins', False),
    (6, 'MI', 'T', 'Abdul El-Sayed', 'D', 'Mike Rogers', False),
    (7, 'NH', 'T', 'Chris Pappas', 'D', 'John Sununu', False),
    (8, 'OH', 'T', 'Sherrod Brown', 'D', 'Jon Husted', True),
    (9, 'TX', 'T', 'James Talarico', 'D', 'Ken Paxton', False),
    (10, 'KS', 'LnR', 'Adam Hamilton', 'D', 'Roger Marshall', False),
    (11, 'NE', 'LkR', 'Dan Osborn', 'I', 'Pete Ricketts', False),
    (12, 'SC', 'LkR', 'Annie Andrews', 'D', 'Darline Graham', False),
]

# (sheet #, district, incumbent note, Cook rating)
HOUSE = [
    (13, 'AZ-1', 'Open seat', 'LnD'), (14, 'CA-13', 'Gray (D)', 'LnD'), (15, 'CA-48', 'Open seat', 'LnD'),
    (16, 'NE-2', 'Open seat', 'LnD'), (17, 'NJ-7', 'Kean (R)', 'LnD'), (18, 'NM-2', 'Vasquez (D)', 'LnD'),
    (19, 'NV-3', 'Lee (D)', 'LnD'), (20, 'NY-3', 'Suozzi (D)', 'LnD'), (21, 'NY-4', 'Gillen (D)', 'LnD'),
    (22, 'OH-1', 'Landsman (D)', 'LnD'), (23, 'TX-28', 'Cuellar (D)', 'LnD'),
    (24, 'AZ-6', 'Ciscomani (R)', 'T'), (25, 'CA-22', 'Valadao (R)', 'T'), (26, 'CO-8', 'Evans (R)', 'T'),
    (27, 'FL-14', 'Castor (D)', 'T'), (28, 'FL-22', 'Open seat', 'T'), (29, 'FL-25', 'Moskowitz (D)', 'T'),
    (30, 'IA-1', 'Miller-Meeks (R)', 'T'), (31, 'IA-3', 'Nunn (R)', 'T'), (32, 'MI-7', 'Barrett (R)', 'T'),
    (33, 'MI-10', 'Open seat', 'T'), (34, 'NC-11', 'Open seat', 'T'), (35, 'NY-17', 'Lawler (R)', 'T'),
    (36, 'OH-7', 'Miller (R)', 'T'), (37, 'OH-9', 'Kaptur (D)', 'T'), (38, 'PA-7', 'Mackenzie (R)', 'T'),
    (39, 'PA-8', 'Bresnahan (R)', 'T'), (40, 'PA-10', 'Perry (R)', 'T'), (41, 'TX-15', 'De La Cruz (R)', 'T'),
    (42, 'TX-34', 'Gonzalez (D)', 'T'), (43, 'VA-2', 'Kiggans (R)', 'T'), (44, 'WA-3', 'Gluesenkamp Perez (D)', 'T'),
    (45, 'WI-3', 'Van Orden (R)', 'T'),
    (46, 'CO-5', 'Crank (R)', 'LnR'), (47, 'FL-13', 'Luna (R)', 'LnR'), (48, 'FL-27', 'Salazar (R)', 'LnR'),
    (49, 'IA-2', 'Open seat', 'LnR'), (50, 'MI-4', 'Huizenga (R)', 'LnR'), (51, 'MT-1', 'Open seat', 'LnR'),
    (52, 'NC-1', 'Davis (D)', 'LnR'), (53, 'TX-35', 'Open seat', 'LnR'), (54, 'VA-1', 'Wittman (R)', 'LnR'),
    (55, 'WI-1', 'Steil (R)', 'LnR'),
]

# Points if correct: [Dem-side pick, GOP pick]. Toss-up 4/4; Lean/Likely favorite 2, underdog 8.
POINTS = {'LkD': (2, 8), 'LnD': (2, 8), 'T': (4, 4), 'LnR': (8, 2), 'LkR': (8, 2)}

# Off-sheet Senate seats that count toward the Big Board seat total and control.
# Every other 2026 seat is checked against the markets each run (see fetch.py) so a
# surprise does not hide here.
SENATE_SEATS_NOT_UP_D = 34   # Dem + caucusing independents not up in 2026

# House seats per state (2020 apportionment), to check that all 435 races were found.
APPORTIONMENT = {
    'AL': 7, 'AK': 1, 'AZ': 9, 'AR': 4, 'CA': 52, 'CO': 8, 'CT': 5, 'DE': 1, 'FL': 28, 'GA': 14, 'HI': 2,
    'ID': 2, 'IL': 17, 'IN': 9, 'IA': 4, 'KS': 4, 'KY': 6, 'LA': 6, 'ME': 2, 'MD': 8, 'MA': 9, 'MI': 13,
    'MN': 8, 'MS': 4, 'MO': 8, 'MT': 2, 'NE': 3, 'NV': 4, 'NH': 2, 'NJ': 12, 'NM': 3, 'NY': 26, 'NC': 14,
    'ND': 1, 'OH': 15, 'OK': 5, 'OR': 6, 'PA': 17, 'RI': 2, 'SC': 7, 'SD': 1, 'TN': 9, 'TX': 38, 'UT': 4,
    'VT': 1, 'VA': 11, 'WA': 10, 'WV': 2, 'WI': 8, 'WY': 1,
}

# The 35 Senate seats up in 2026 (33 regular + Ohio and Florida specials).
SENATE_UP = ['AL', 'AK', 'AR', 'CO', 'DE', 'FL', 'GA', 'ID', 'IL', 'IA', 'KS', 'KY', 'LA', 'ME', 'MA', 'MI',
             'MN', 'MS', 'MT', 'NE', 'NH', 'NJ', 'NM', 'NC', 'OH', 'OK', 'OR', 'RI', 'SC', 'SD', 'TN', 'TX',
             'VA', 'WV', 'WY']

# Party for candidates in races that only have person markets (no party tags).
# CA-40: two Republican incumbents drawn into one district; checked by hand.
CANDIDATE_PARTY = {'ken calvert': 'R', 'young kim': 'R'}
