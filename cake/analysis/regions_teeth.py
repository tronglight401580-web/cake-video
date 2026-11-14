import cv2
import numpy as np
from .regions import register_region

INNER_LIP = (78, 191, 80, 81, 82, 13, 312, 311, 310, 415, 308, 324, 318, 402, 317, 14, 87, 178, 88, 95)

@register_region('teeth')
def teeth_region(faces, shape):
    mask = np.zeros(shape, np.uint8)
    for face in faces:
        points = np.asarray(face)
        if len(points) > max(INNER_LIP) and np.isfinite(points[list(INNER_LIP)]).all():
            cv2.fillPoly(mask, [np.rint(points[list(INNER_LIP)]).astype(np.int32)], 255)
    return cv2.GaussianBlur(mask.astype(np.float32) / 255, (3, 3), 0)
