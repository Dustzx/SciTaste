"""No-call checks of the conditional code guarantee and fallback behavior."""
import itertools,json
import numpy as np
from cvpr_count_code import MATRIX,decode,valid_count,vote

def main():
    # Every 4-row submatrix has rank 3, so any nonzero difference has >=4 nonzero outputs.
    assert all(np.linalg.matrix_rank(MATRIX[list(t)])==3 for t in itertools.combinations(range(7),4))
    assert np.count_nonzero(MATRIX@np.array([1,-1,0]))==4
    checked=0
    for x in itertools.product(range(4),repeat=3):
        y=(MATRIX@x).tolist();assert decode(y)['cells']==list(x)
        for i in range(7):
            for error in [-1,1,None]:
                z=y.copy();z[i]=None if error is None else y[i]+error
                decoded=decode(z);assert decoded['accepted'] and decoded['cells']==list(x),(x,z,decoded);checked+=1
    assert decode([None]*7)['answer'] is None
    assert not decode([0,0,0,20,21,22,23])['accepted']
    assert decode([0,0,0,20,21,22,23])['answer']==23
    assert vote([2,3,3,2,None,None,None])==2
    assert vote([None]*7) is None and not valid_count(True) and not valid_count(-1)
    print(json.dumps({'code_minimum_distance':4,'single_error_or_erasure_cases':checked,'paid_calls':0,'conditional_not_perceptual_guarantee':True}))

if __name__=='__main__':main()
