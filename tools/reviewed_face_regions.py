"""Bind detected faces to reviewed body regions without deciding identity."""
import math


def region_assignment(record, image_sha256, expected_ids, face_boxes):
    if record.get('image_sha256') != image_sha256:
        raise ValueError('REVIEWED_REGION_IMAGE_SHA_MISMATCH')
    if not record.get('reviewer') or not record.get('reviewed_at'):
        raise ValueError('REVIEWED_REGION_PROVENANCE_MISSING')
    rows = record.get('regions') or []
    ids = [r.get('character_id') for r in rows]
    if len(ids) != len(set(ids)) or set(ids) != set(expected_ids):
        raise ValueError('REVIEWED_REGION_CHARACTER_COVERAGE')
    result = {}
    for row in rows:
        box = row.get('bbox') or []
        if (len(box) != 4 or not all(isinstance(v, (int, float)) and math.isfinite(v) for v in box)
                or not (0 <= box[0] < box[2] and 0 <= box[1] < box[3])):
            raise ValueError('REVIEWED_REGION_INVALID_BBOX')
        matches = []
        for i, face in enumerate(face_boxes):
            x, y = (face[0]+face[2])/2, (face[1]+face[3])/2
            if box[0] <= x <= box[2] and box[1] <= y <= box[3]:
                matches.append(i)
        if len(matches) != 1 or matches[0] in result.values():
            raise ValueError('REVIEWED_REGION_AMBIGUOUS_OR_MISSING_FACE')
        result[row['character_id']] = matches[0]
    return result
