import copy
import pytest
from tools.reviewed_face_regions import region_assignment


def record():
    return {'image_sha256':'exact', 'reviewer':'test reviewer','reviewed_at':'now',
            'regions':[{'character_id':'A','bbox':[0,0,10,10]},
                       {'character_id':'B','bbox':[20,0,30,10]}]}


def test_body_association_not_similarity_order():
    assert region_assignment(record(),'exact',['A','B'],[[22,2,28,8],[2,2,8,8]]) == {'A':1,'B':0}


@pytest.mark.parametrize('mutation,expected',[
    (lambda r:r.update(image_sha256='old'),'SHA_MISMATCH'),
    (lambda r:r.update(reviewer=''),'PROVENANCE'),
    (lambda r:r['regions'].pop(),'COVERAGE'),
    (lambda r:r['regions'][0].update(bbox=[0,0,30,10]),'AMBIGUOUS'),
    (lambda r:r['regions'][0].update(bbox=[40,0,50,10]),'MISSING'),
    (lambda r:r['regions'][0].update(bbox=[0,0,float('nan'),10]),'INVALID'),
])
def test_fail_closed(mutation,expected):
    r=copy.deepcopy(record());mutation(r)
    with pytest.raises(ValueError,match=expected):
        region_assignment(r,'exact',['A','B'],[[2,2,8,8],[22,2,28,8]])
