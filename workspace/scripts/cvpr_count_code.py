"""Integer agreement decoding for seven additive queries on three disjoint cells.

Conditional guarantee only: if a true ownership count vector exists and at most
one query is erroneous/erased, it is recoverable. This does not certify perception.
"""
import itertools
from collections import Counter

import numpy as np

MATRIX=np.array([[1,0,0],[0,1,0],[0,0,1],[1,1,0],[0,1,1],[1,0,1],[1,1,1]],dtype=int)
TRIPLES=[tuple(t) for t in itertools.combinations(range(7),3) if abs(np.linalg.det(MATRIX[list(t)]))>.5]


def valid_count(value):
    return type(value) is int and 0<=value<=1000000


def vote(values):
    usable=[v for v in values if valid_count(v)]
    if not usable:return None
    counts=Counter(usable);top=max(counts.values())
    # Fixed tie break uses first (identity) response among tied modes, no labels.
    return next(v for v in usable if counts[v]==top)


def decode(values):
    assert len(values)==7
    candidates=set()
    for t in TRIPLES:
        if not all(valid_count(values[i]) for i in t):continue
        x=np.linalg.solve(MATRIX[list(t)].astype(float),np.array([values[i] for i in t],dtype=float))
        rounded=np.rint(x).astype(int)
        if np.max(np.abs(x-rounded))<1e-7 and np.all(rounded>=0):candidates.add(tuple(int(v) for v in rounded))
    ranked=[]
    for x in candidates:
        y=MATRIX@x
        mismatch=[i for i in range(7) if not valid_count(values[i]) or values[i]!=int(y[i])]
        ranked.append((len(mismatch),x,mismatch))
    ranked.sort()
    fallback=values[-1] if valid_count(values[-1]) else None
    if not ranked:return {'answer':fallback,'accepted':False,'reason':'No nonnegative integer candidate','cells':None,'mismatches':None}
    best=ranked[0];unique=len(ranked)==1 or ranked[1][0]>best[0]
    accepted=unique and best[0]<=1
    return {'answer':sum(best[1]) if accepted else fallback,'accepted':accepted,
            'reason':'Unique integer candidate with <=1 mismatch/erasure' if accepted else 'Ambiguous or >1 inconsistency; retain global answer',
            'cells':list(best[1]) if accepted else None,'mismatches':best[2],
            'best_mismatch_count':best[0],'candidate_count':len(ranked)}
