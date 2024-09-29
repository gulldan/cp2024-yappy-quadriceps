from app.clustering import cluster_videos
import pandas as pd

def test_cluster_videos():
    data = pd.DataFrame({
        'uuid': ['uuid1', 'uuid2', 'uuid3', 'uuid4', 'uuid5'],
        'link': [
            "http://example.com/video1.mp4",
            "http://example.com/video2.mp4",
            "http://example.com/video3.mp4",
            "http://example.com/video4.mp4",
            "http://example.com/video5.mp4"
        ],
        'duration': [10, 20, 30, 40, 50],
        'size': [1000, 2000, 3000, 4000, 5000],
        'md5': ['hash1', 'hash2', 'hash3', 'hash4', 'hash5']
    })
    
    result = cluster_videos(data, n_clusters=2)
    assert 'clusters' in result
    assert len(result['clusters']) == 2
    total_videos = sum(len(videos) for videos in result['clusters'].values())
    assert total_videos == 5
