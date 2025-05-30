# stdlib
from os import makedirs
from os.path import basename, exists, join, splitext

import cv2
import numpy as np
from skimage import measure

# 3p
from tqdm import tqdm

# project
# from text_detector.main_text_detector import TextDetector
from utils import get_files, load_image, save_file


class PanelExtractor:
    def __init__(
        self,
        keep_text=False,
        min_pct_panel=2,
        max_pct_panel=90,
        paper_th=0.35,
    ):
        self.keep_text = keep_text
        assert (
            min_pct_panel < max_pct_panel
        ), "Minimum percentage must be smaller than maximum percentage"
        self.min_panel = min_pct_panel / 100
        self.max_panel = max_pct_panel / 100
        self.paper_th = paper_th

        print("Done!")

    def _generate_panel_blocks(self, img):
        img = img if len(img.shape) == 2 else img[:, :, 0]
        blur = cv2.GaussianBlur(img, (5, 5), 0)
        thresh = cv2.threshold(blur, 230, 255, cv2.THRESH_BINARY)[1]
        cv2.rectangle(thresh, (0, 0), tuple(img.shape[::-1]), (0, 0, 0), 10)
        num_labels, labels, stats, centroids = cv2.connectedComponentsWithStats(
            thresh, 4, cv2.CV_32S
        )
        ind = np.argsort(
            stats[:, 4],
        )[
            ::-1
        ][1]
        panel_block_mask = ((labels == ind) * 255).astype("uint8")
        return panel_block_mask

    def _generate_panel_blocks_adaptive(self, img):
        img = img if len(img.shape) == 2 else img[:, :, 0]
        blur = cv2.GaussianBlur(img, (5, 5), 0)

        # Apply adaptive thresholding
        thresh = cv2.adaptiveThreshold(
            blur, 255, cv2.ADAPTIVE_THRESH_MEAN_C, cv2.THRESH_BINARY, 11, 2
        )

        # Find contours
        contours, _ = cv2.findContours(
            thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
        )

        # Find the largest contour (panel block)
        panel_block_contour = max(contours, key=cv2.contourArea)

        # Create a mask for the panel block
        panel_block_mask = np.zeros_like(img)
        cv2.drawContours(panel_block_mask, [panel_block_contour], -1, 255, cv2.FILLED)

        return panel_block_mask

    def generate_contours(self, img):
        block_mask = self._generate_panel_blocks_adaptive(img)
        cv2.rectangle(
            block_mask, (0, 0), tuple(block_mask.shape[::-1]), (255, 255, 255), 10
        )

        # detect contours
        contours, hierarchy = cv2.findContours(
            block_mask, cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE
        )
        good_contours = []

        for c in contours:
            area = cv2.contourArea(c)
            img_area = img.shape[0] * img.shape[1]

            # if the contour is very small or very big, it's likely wrongly detected
            if area < (self.min_panel * img_area) or area > (self.max_panel * img_area):
                continue

            good_contours.append(self.c2j(c, img.shape[0], img.shape[1]))

        # If no good contours are found, create a contour covering the entire image
        if not good_contours or len(good_contours) == 1:
            x = 0
            y = 0
            w = img.shape[1]
            h = img.shape[0]
            entire_image_contour_j = {
                "x": 0,
                "y": 0,
                "width": w,
                "height": h,
                # "path": path
                "path": f"{x} {y}, {x+w} {y}, {x+w} {y+h}, {x} {y+h}, {x} {y}",
            }
            good_contours = [entire_image_contour_j]

        return good_contours

    def c2j(self, c, img_H, img_W):
        x, y, w, h = cv2.boundingRect(c)
        x = x / img_W * 100
        y = y / img_H * 100
        w = w / img_W * 100
        h = h / img_H * 100
        return {
            "x": x,
            "y": y,
            "width": w,
            "height": h,
            # "path": path
            "path": f"{x} {y}, {x+w} {y}, {x+w} {y+h}, {x} {y+h}, {x} {y}",
        }

    def extract(self, folder):
        print("Loading images ... ", end="")
        image_list, _, _ = get_files(folder)
        print("Done!")

        import json
        import os

        img_dict_path = os.path.join(folder, "img_dict.json")
        with open(img_dict_path, "r") as f:
            img_dict = json.load(f)

        pages = []
        for i in tqdm(sorted(image_list), desc="extracting panels"):
            img = load_image(i)

            contours = self.generate_contours(img)
            print(basename(i), len(contours))
            print(img_dict[basename(i)])
            pages.append(
                {
                    "page_index": i,
                    "image": img_dict[basename(i)],
                    "panels": sorted(contours, key=lambda p: p["y"]),
                }
            )

        # save pages on disk as json
        _final = {
            "title": "",
            "author": [],
            "tags": [],
            "pageCount": len(pages),
            "pages": pages,
        }
        # Directly from dictionary
        # save_file(_final, 'output.json')

        return _final
