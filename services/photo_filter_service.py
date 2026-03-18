from __future__ import annotations

import math
import shutil
import time
from dataclasses import dataclass
from pathlib import Path

from config import (
    CLUSTER_MERGE_AVERAGE_THRESHOLD,
    CLUSTER_MERGE_BEST_THRESHOLD,
    HASH_SIZE,
    HIST_BINS,
    IMAGE_EXTENSIONS,
    MIN_ORB_KEYPOINTS,
    ORB_FEATURES,
    ORB_GOOD_MATCH_DISTANCE,
    THUMBNAIL_SIZE,
)

try:
    import numpy as np
except ModuleNotFoundError as exc:
    raise SystemExit(
        "NumPy is missing. Install it with: pip install numpy"
    ) from exc

try:
    import cv2
except ModuleNotFoundError as exc:
    raise SystemExit(
        "OpenCV is missing. Install it with: pip install opencv-python"
    ) from exc


@dataclass
class PhotoCandidate:
    path: Path
    quality_score: float
    cluster_id: int = -1
    cluster_rank: int = -1
    is_cluster_winner: bool = False
    is_final_selection: bool = False


@dataclass
class PhotoFeatures:
    histogram: np.ndarray
    color_thumbnail: np.ndarray
    gray_thumbnail: np.ndarray
    dhash: np.ndarray
    orb_descriptors: np.ndarray | None
    orb_keypoint_count: int


@dataclass
class PairEvidence:
    similarity_score: float
    hash_similarity: float
    gray_ssim_similarity: float
    good_orb_matches: int
    average_match_distance: float


def _has_usable_orb_descriptors(features: PhotoFeatures) -> bool:
    return (
        features.orb_descriptors is not None
        and features.orb_keypoint_count >= MIN_ORB_KEYPOINTS
    )


def list_images(folder: Path) -> list[Path]:
    return sorted(
        file_path
        for file_path in folder.iterdir()
        if file_path.is_file() and file_path.suffix.lower() in IMAGE_EXTENSIONS
    )


def load_image(path: Path) -> np.ndarray:
    image = cv2.imread(str(path))
    if image is None:
        raise ValueError(f"Could not open image: {path}")
    return image


def compute_quality_score(image: np.ndarray) -> float:
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    sharpness = cv2.Laplacian(gray, cv2.CV_64F).var()

    brightness = float(np.mean(gray))
    exposure_balance = max(0.0, 1.0 - abs(brightness - 127.5) / 127.5)

    contrast = float(np.std(gray))

    denoised = cv2.GaussianBlur(gray, (3, 3), 0)
    noise_estimate = float(
        np.mean(np.abs(gray.astype(np.float32) - denoised.astype(np.float32)))
    )
    noise_penalty = 1.0 / (1.0 + noise_estimate)

    return (
        0.45 * math.log1p(sharpness)
        + 0.20 * (contrast / 64.0)
        + 0.20 * exposure_balance
        + 0.15 * noise_penalty
    )


def compute_difference_hash(gray_image: np.ndarray) -> np.ndarray:
    hash_source = cv2.resize(
        gray_image,
        (HASH_SIZE + 1, HASH_SIZE),
        interpolation=cv2.INTER_AREA,
    )
    return (hash_source[:, 1:] > hash_source[:, :-1]).astype(np.uint8).flatten()


def build_photo_features(image: np.ndarray, orb_detector: cv2.ORB) -> PhotoFeatures:
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)

    histogram = cv2.calcHist(
        [hsv],
        [0, 1, 2],
        None,
        HIST_BINS,
        [0, 180, 0, 256, 0, 256],
    )
    histogram = cv2.normalize(histogram, histogram).flatten().astype(np.float32)

    resized_color = cv2.resize(image, THUMBNAIL_SIZE, interpolation=cv2.INTER_AREA)
    color_thumbnail = (
        cv2.cvtColor(resized_color, cv2.COLOR_BGR2LAB).astype(np.float32) / 255.0
    )

    resized_gray = cv2.resize(gray, THUMBNAIL_SIZE, interpolation=cv2.INTER_AREA)
    gray_thumbnail = resized_gray.astype(np.float32) / 255.0

    keypoints, orb_descriptors = orb_detector.detectAndCompute(gray, None)
    keypoint_count = len(keypoints)

    return PhotoFeatures(
        histogram=histogram,
        color_thumbnail=color_thumbnail,
        gray_thumbnail=gray_thumbnail,
        dhash=compute_difference_hash(gray),
        orb_descriptors=orb_descriptors,
        orb_keypoint_count=keypoint_count,
    )


def compute_histogram_similarity(
    features_a: PhotoFeatures,
    features_b: PhotoFeatures,
) -> float:
    correlation = float(
        cv2.compareHist(
            features_a.histogram,
            features_b.histogram,
            cv2.HISTCMP_CORREL,
        )
    )
    return max(0.0, min(1.0, (correlation + 1.0) / 2.0))


def compute_color_layout_similarity(
    features_a: PhotoFeatures,
    features_b: PhotoFeatures,
) -> float:
    mean_abs_difference = float(
        np.mean(np.abs(features_a.color_thumbnail - features_b.color_thumbnail))
    )
    return max(0.0, 1.0 - mean_abs_difference)


def compute_gray_ssim_similarity(
    features_a: PhotoFeatures,
    features_b: PhotoFeatures,
) -> float:
    image_a = features_a.gray_thumbnail
    image_b = features_b.gray_thumbnail

    mean_a = float(np.mean(image_a))
    mean_b = float(np.mean(image_b))
    variance_a = float(np.var(image_a))
    variance_b = float(np.var(image_b))
    covariance = float(np.mean((image_a - mean_a) * (image_b - mean_b)))

    c1 = 0.01 ** 2
    c2 = 0.03 ** 2

    numerator = (2.0 * mean_a * mean_b + c1) * (2.0 * covariance + c2)
    denominator = (mean_a ** 2 + mean_b ** 2 + c1) * (variance_a + variance_b + c2)
    if math.isclose(denominator, 0.0):
        return 0.0

    ssim = numerator / denominator
    return max(0.0, min(1.0, (ssim + 1.0) / 2.0))


def compute_hash_similarity(
    features_a: PhotoFeatures,
    features_b: PhotoFeatures,
) -> float:
    hamming_distance = int(np.count_nonzero(features_a.dhash != features_b.dhash))
    return 1.0 - (hamming_distance / float(features_a.dhash.size))


def compute_orb_similarity(
    features_a: PhotoFeatures,
    features_b: PhotoFeatures,
) -> float:
    if not _has_usable_orb_descriptors(features_a):
        return 0.0

    if not _has_usable_orb_descriptors(features_b):
        return 0.0

    descriptors_a = features_a.orb_descriptors
    descriptors_b = features_b.orb_descriptors
    matcher = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=False)
    knn_matches = matcher.knnMatch(descriptors_a, descriptors_b, k=2)

    good_matches = 0
    for match_pair in knn_matches:
        if len(match_pair) < 2:
            continue
        best_match, second_match = match_pair
        if best_match.distance <= ORB_GOOD_MATCH_DISTANCE and (
            best_match.distance < 0.75 * second_match.distance
        ):
            good_matches += 1

    normalizer = max(1, min(len(descriptors_a), len(descriptors_b)))
    return min(1.0, good_matches / float(normalizer))


def compute_orb_match_evidence(
    features_a: PhotoFeatures,
    features_b: PhotoFeatures,
) -> tuple[int, float]:
    if not _has_usable_orb_descriptors(features_a):
        return 0, 100.0

    if not _has_usable_orb_descriptors(features_b):
        return 0, 100.0

    descriptors_a = features_a.orb_descriptors
    descriptors_b = features_b.orb_descriptors
    matcher = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=True)
    matches = sorted(
        matcher.match(descriptors_a, descriptors_b),
        key=lambda match: match.distance,
    )
    if not matches:
        return 0, 100.0

    good_matches = sum(1 for match in matches if match.distance <= ORB_GOOD_MATCH_DISTANCE)
    top_matches = matches[: min(10, len(matches))]
    average_match_distance = float(
        np.mean([match.distance for match in top_matches])
    )
    return good_matches, average_match_distance


def compute_pair_similarity(
    features_a: PhotoFeatures,
    features_b: PhotoFeatures,
) -> float:
    histogram_similarity = compute_histogram_similarity(features_a, features_b)
    color_layout_similarity = compute_color_layout_similarity(features_a, features_b)
    gray_ssim_similarity = compute_gray_ssim_similarity(features_a, features_b)
    hash_similarity = compute_hash_similarity(features_a, features_b)
    orb_similarity = compute_orb_similarity(features_a, features_b)

    combined_similarity = (
        0.22 * histogram_similarity
        + 0.28 * color_layout_similarity
        + 0.25 * gray_ssim_similarity
        + 0.15 * orb_similarity
        + 0.10 * hash_similarity
    )

    if hash_similarity >= 0.88 and color_layout_similarity >= 0.78:
        combined_similarity = max(combined_similarity, 0.82)

    if orb_similarity >= 0.10 and gray_ssim_similarity >= 0.72:
        combined_similarity = max(combined_similarity, 0.78)

    return max(0.0, min(1.0, combined_similarity))


def compute_pair_evidence(
    features_a: PhotoFeatures,
    features_b: PhotoFeatures,
) -> PairEvidence:
    hash_similarity = compute_hash_similarity(features_a, features_b)
    gray_ssim_similarity = compute_gray_ssim_similarity(features_a, features_b)
    similarity_score = compute_pair_similarity(features_a, features_b)
    good_orb_matches, average_match_distance = compute_orb_match_evidence(
        features_a,
        features_b,
    )

    return PairEvidence(
        similarity_score=similarity_score,
        hash_similarity=hash_similarity,
        gray_ssim_similarity=gray_ssim_similarity,
        good_orb_matches=good_orb_matches,
        average_match_distance=average_match_distance,
    )


def build_similarity_matrix(photo_features: list[PhotoFeatures]) -> np.ndarray:
    num_photos = len(photo_features)
    similarity_matrix = np.eye(num_photos, dtype=np.float32)

    for left_index in range(num_photos):
        for right_index in range(left_index + 1, num_photos):
            evidence = compute_pair_evidence(
                photo_features[left_index],
                photo_features[right_index],
            )
            similarity = evidence.similarity_score

            if evidence.hash_similarity >= 0.95 and evidence.gray_ssim_similarity >= 0.90:
                similarity = max(similarity, 0.95)

            if evidence.good_orb_matches >= 90 and evidence.average_match_distance <= 32.0:
                similarity = max(similarity, 0.90)

            similarity_matrix[left_index, right_index] = similarity
            similarity_matrix[right_index, left_index] = similarity

    return similarity_matrix


def compute_cluster_link_scores(
    left_cluster: list[int],
    right_cluster: list[int],
    similarity_matrix: np.ndarray,
) -> tuple[float, float]:
    pair_scores = [
        float(similarity_matrix[left_index, right_index])
        for left_index in left_cluster
        for right_index in right_cluster
    ]
    return float(np.mean(pair_scores)), float(np.max(pair_scores))


def cluster_photo_indices(photo_features: list[PhotoFeatures]) -> list[list[int]]:
    similarity_matrix = build_similarity_matrix(photo_features)
    clusters: list[list[int]] = [[index] for index in range(len(photo_features))]

    while True:
        best_pair: tuple[int, int] | None = None
        best_average_score = -1.0
        best_max_score = -1.0

        for left_index in range(len(clusters)):
            for right_index in range(left_index + 1, len(clusters)):
                average_score, max_score = compute_cluster_link_scores(
                    clusters[left_index],
                    clusters[right_index],
                    similarity_matrix,
                )
                if max_score < CLUSTER_MERGE_BEST_THRESHOLD:
                    continue
                if average_score < CLUSTER_MERGE_AVERAGE_THRESHOLD:
                    continue
                if average_score > best_average_score or (
                    math.isclose(average_score, best_average_score)
                    and max_score > best_max_score
                ):
                    best_pair = (left_index, right_index)
                    best_average_score = average_score
                    best_max_score = max_score

        if best_pair is None:
            break

        left_index, right_index = best_pair
        clusters[left_index] = sorted(clusters[left_index] + clusters[right_index])
        del clusters[right_index]

    return sorted(clusters, key=lambda cluster: cluster[0])


def assign_clusters_to_candidates(
    candidates: list[PhotoCandidate],
    clustered_indices: list[list[int]],
) -> list[list[PhotoCandidate]]:
    candidate_clusters: list[list[PhotoCandidate]] = []

    for cluster in clustered_indices:
        group = [candidates[index] for index in cluster]
        group.sort(key=lambda candidate: candidate.quality_score, reverse=True)
        candidate_clusters.append(group)

    candidate_clusters.sort(
        key=lambda group: group[0].quality_score,
        reverse=True,
    )

    for cluster_id, group in enumerate(candidate_clusters):
        for rank, candidate in enumerate(group, start=1):
            candidate.cluster_id = cluster_id
            candidate.cluster_rank = rank
        group[0].is_cluster_winner = True

    return candidate_clusters


def select_final_photos(
    candidate_clusters: list[list[PhotoCandidate]],
    num_to_extract: int,
) -> list[PhotoCandidate]:
    cluster_winners = [group[0] for group in candidate_clusters]
    cluster_winners.sort(key=lambda candidate: candidate.quality_score, reverse=True)

    final_selection = cluster_winners[: min(num_to_extract, len(cluster_winners))]
    for candidate in final_selection:
        candidate.is_final_selection = True

    return final_selection


def export_results(selected: list[PhotoCandidate], output_dir: Path) -> None:
    if output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    for rank, candidate in enumerate(selected, start=1):
        destination = output_dir / f"{rank:02d}_{candidate.path.name}"
        shutil.copy2(candidate.path, destination)


def print_cluster_report(candidate_clusters: list[list[PhotoCandidate]]) -> None:
    print("Detected clusters:")
    for cluster_id, group in enumerate(candidate_clusters):
        print(f"  Cluster {cluster_id} ({len(group)} photos)")
        for candidate in group:
            if candidate.is_final_selection:
                status = "FINAL_SELECTION"
            elif candidate.is_cluster_winner:
                status = "CLUSTER_WINNER"
            else:
                status = "DISCARDED_IN_CLUSTER"

            print(
                f"    - {candidate.path.name} | "
                f"quality={candidate.quality_score:.3f} | "
                f"cluster_rank={candidate.cluster_rank} | "
                f"{status}"
            )
        print()


def resolve_runtime_paths(
    source_path: str | Path,
    destination_path: str | Path,
) -> tuple[Path, Path]:
    input_dir = Path(source_path).expanduser().resolve()
    output_dir = Path(destination_path).expanduser().resolve()

    if not input_dir.exists():
        raise SystemExit(f"Source folder does not exist: {input_dir}")

    if not input_dir.is_dir():
        raise SystemExit(f"Source path is not a folder: {input_dir}")

    if output_dir == input_dir or output_dir in input_dir.parents:
        raise SystemExit(
            "Destination folder cannot be the same as the source folder or one of its parent folders."
        )

    return input_dir, output_dir


def filter_photos(
    num_photos_to_extract: int,
    source_path: str | Path,
    destination_path: str | Path,
) -> list[PhotoCandidate]:
    try:
        requested_photo_count = int(num_photos_to_extract)
    except (TypeError, ValueError) as exc:
        raise SystemExit("num_photos_to_extract must be an integer.") from exc

    if requested_photo_count <= 0:
        raise SystemExit("num_photos_to_extract must be greater than zero.")

    input_dir, output_dir = resolve_runtime_paths(source_path, destination_path)
    start_time = time.perf_counter()
    image_paths = list_images(input_dir)
    if not image_paths:
        raise SystemExit(f"No images were found in: {input_dir}")

    orb_detector = cv2.ORB_create(nfeatures=ORB_FEATURES)

    candidates: list[PhotoCandidate] = []
    photo_features: list[PhotoFeatures] = []

    for image_path in image_paths:
        image = load_image(image_path)
        candidates.append(
            PhotoCandidate(
                path=image_path,
                quality_score=compute_quality_score(image),
            )
        )
        photo_features.append(build_photo_features(image, orb_detector))

    clustered_indices = cluster_photo_indices(photo_features)
    candidate_clusters = assign_clusters_to_candidates(candidates, clustered_indices)
    final_selection = select_final_photos(candidate_clusters, requested_photo_count)

    export_results(final_selection, output_dir)
    elapsed_time = time.perf_counter() - start_time

    print(f"Photos analyzed: {len(candidates)}")
    print(f"Clusters detected: {len(candidate_clusters)}")
    print(f"Cluster winners: {len(candidate_clusters)}")
    print(f"Photos selected: {len(final_selection)}")
    print(f"Output folder: {output_dir}")
    print(f"Processing time: {elapsed_time:.3f} seconds")
    print()

    print_cluster_report(candidate_clusters)

    print("Final selection:")
    for rank, candidate in enumerate(final_selection, start=1):
        print(
            f"{rank}. {candidate.path.name} | "
            f"cluster={candidate.cluster_id} | "
            f"quality={candidate.quality_score:.3f}"
        )

    return final_selection
