"""Diagnostic comparison of MediaPipe and ONNX on one 256x256 RGB image."""
import numpy as np
import cv2
import onnxruntime as ort
from mediapipe.tasks.python import BaseOptions, vision
from test_seg_gpu import ROOT, frame_at, mediapipe_segment

image = cv2.resize(frame_at(ROOT / 'samples/asian_closeup_v_101040.mp4', 2), (256, 256))
task = vision.ImageSegmenter.create_from_options(vision.ImageSegmenterOptions(
    base_options=BaseOptions(model_asset_buffer=(ROOT / 'models/selfie_multiclass_256x256.tflite').read_bytes()),
    running_mode=vision.RunningMode.IMAGE, output_confidence_masks=True))
ref = mediapipe_segment(image, task)
s = ort.InferenceSession((ROOT / 'models/selfie_multiclass_256x256.onnx').read_bytes(), providers=['DmlExecutionProvider'])
for name, x in [('rgb01', image.astype('float32')/255), ('rgb11', image.astype('float32')/127.5-1),
                ('rgb255', image.astype('float32')), ('bgr01', image[...,::-1].astype('float32')/255)]:
    y = s.run(None, {s.get_inputs()[0].name:x[None]})[0][0]
    z = np.exp(y-y.max(-1,keepdims=True));z /= z.sum(-1,keepdims=True)
    print(name,'raw sum',y.sum(-1).mean(),'raw range',y.min(),y.max(), 'soft sum',z.sum(-1).mean())
    for label, j, a in [('face',3,ref[0]),('body',2,ref[1])]:
        b=z[...,j]
        print(label,'mean',np.abs(a-b).mean(),'soft IoU',np.minimum(a,b).sum()/np.maximum(a,b).sum(), 'ref range',a.min(),a.max())
task.close()
