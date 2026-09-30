import os
import subprocess
import glob

videos = [
    'gf_15_living_knit_silhouette.mp4',
    'gf_01_living_deep_vneck.mp4',
    'gf_02_living_wrap_knit.mp4',
    'sec_canonical_living_desk.mp4',
    'sec_09_living_silk_unbutton.mp4',
    'sec_02_living_silk_desk.mp4'
]

print("🚀 Starting batch mobile video optimization on EC2...")

for v in videos:
    src = f'/home/ubuntu/{v}'
    opt = f'/home/ubuntu/opt_{v}'
    if not os.path.exists(src):
        print(f"Skipping {v} (not found)")
        continue
        
    print(f"Optimizing {v}...")
    cmd = [
        'ffmpeg', '-y', '-i', src,
        '-c:v', 'libx264', '-crf', '22', '-preset', 'fast',
        '-pix_fmt', 'yuv420p', '-movflags', '+faststart',
        '-maxrate', '3.5M', '-bufsize', '7M',
        opt
    ]
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    
    orig_sz = os.path.getsize(src) // 1024
    opt_sz = os.path.getsize(opt) // 1024
    print(f"✅ {v}: {orig_sz} KB -> {opt_sz} KB ({(opt_sz/orig_sz)*100:.1f}%)")
    
    # Overwrite original
    os.replace(opt, src)
    
    # Docker copy to container
    subprocess.run(f"sudo docker cp {src} samantha-app:/app/static/gallery/{v}", shell=True, check=True)
    if v == 'gf_15_living_knit_silhouette.mp4':
        subprocess.run(f"sudo docker cp {src} samantha-app:/app/static/gallery/gf_minji_living_breathing.mp4", shell=True, check=True)

print("\n🎉 ALL VIDEOS OPTIMIZED FOR MOBILE STREAMING AND ZERO CRASHES!")
