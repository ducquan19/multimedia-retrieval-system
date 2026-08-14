import json
import logging
from pathlib import Path
from elasticsearch import Elasticsearch, helpers

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

def build_es_index(data_root: Path, es_url: str):
    keyframes_path = data_root / "keyframes.json"
    asr_dir = data_root / "asr"
    
    if not keyframes_path.exists():
        logger.error("keyframes.json not found at %s", keyframes_path)
        return

    logger.info("Loading keyframes manifest...")
    with open(keyframes_path, "r", encoding="utf-8") as f:
        manifest = json.load(f)
    
    keyframes = manifest.get("keyframes", [])
    
    # Map segment_id -> list of global_idxs
    segment_to_idx = {}
    for idx, kf in enumerate(keyframes):
        seg = kf.get("segment_id")
        if seg:
            segment_to_idx.setdefault(seg, []).append(idx)
            
    # Load ASR texts
    logger.info("Scanning ASR directory...")
    segment_texts = {}
    if asr_dir.exists():
        for video_dir in asr_dir.iterdir():
            if not video_dir.is_dir():
                continue
            video_id = video_dir.name
            for asr_file in video_dir.glob("*.json"):
                shot_id = asr_file.stem  # e.g. S00006
                segment_id = f"{video_id}_{shot_id}"
                
                try:
                    with open(asr_file, "r", encoding="utf-8") as f:
                        asr_data = json.load(f)
                        text = asr_data.get("text", "").strip()
                        if text:
                            segment_texts[segment_id] = text
                except Exception as e:
                    logger.error("Failed to read %s: %s", asr_file, e)
    
    logger.info("Found ASR texts for %d segments.", len(segment_texts))
    
    # Update keyframes with ASR text
    updated_count = 0
    actions = []
    
    for segment_id, text in segment_texts.items():
        if segment_id in segment_to_idx:
            for idx in segment_to_idx[segment_id]:
                keyframes[idx]["asr_text"] = text
                updated_count += 1
                
                # Elasticsearch action
                actions.append({
                    "_index": "keyframes_metadata",
                    "_id": str(idx),
                    "_source": {
                        "faiss_id": idx,
                        "asr_text": text
                    }
                })
                
    logger.info("Updated %d keyframes with ASR text.", updated_count)
    
    # Save back to keyframes.json so UI can see it
    logger.info("Saving updated keyframes.json...")
    with open(keyframes_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
        
    # Push to Elasticsearch
    logger.info("Connecting to Elasticsearch at %s...", es_url)
    es = Elasticsearch(es_url)
    
    try:
        es.ping()
    except Exception as e:
        logger.error("Could not connect to Elasticsearch. Is it running? %s", e)
        return

    # Delete index if exists, then recreate with BM25 analyzer for Vietnamese
    index_name = "keyframes_metadata"
    if es.indices.exists(index=index_name):
        es.indices.delete(index=index_name)
        
    # Mapping
    mapping = {
        "mappings": {
            "properties": {
                "faiss_id": {"type": "integer"},
                "asr_text": {"type": "text"}
            }
        }
    }
    es.indices.create(index=index_name, body=mapping)
    
    logger.info("Indexing %d documents into Elasticsearch...", len(actions))
    helpers.bulk(es, actions)
    logger.info("Done building Elasticsearch index!")

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-root", type=str, default="./data")
    parser.add_argument("--es-url", type=str, default="http://localhost:9200")
    args = parser.parse_args()
    build_es_index(Path(args.data_root), args.es_url)
