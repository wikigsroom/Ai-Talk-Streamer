"""Read one real CPU training batch; no CUDA allocation or model training."""
import os
os.environ['CUDA_VISIBLE_DEVICES']=''
from bench_common import *

def main():
 import random,torch
 from torch.utils.data import default_collate
 src=R/'src/lipsync-benchmark/feather';sys.path.insert(0,str(src))
 from model import create_model,visual_model_config
 from dataset_mouth_roi import TemporalMouthRoiDataset
 torch.set_num_threads(2);random.seed(20261028);np.random.seed(20261028);torch.manual_seed(20261028)
 net=create_model('feathertalk');config=visual_model_config(net)
 dataset=TemporalMouthRoiDataset(str(O/'training'),image_size=net.image_size,audio_half_window=net.audio_half_window,raw_hubert_audio=net.raw_hubert_audio)
 selected=[0,1,197,198,199,200,395,396,397,398,399,400,len(dataset)//2,len(dataset)-3,len(dataset)-2,len(dataset)-1]
 tensors=default_collate([dataset[i] for i in selected]);inp=manifest()
 checks={'frames_8000':dataset.frame_count==8000,'ranges_40':len(dataset.clip_ranges)==40,'temporal_pairs_7960':len(dataset)==7960,'all_pairs_within_source_clips':all(int(dataset.clip_starts[i])==int(dataset.clip_starts[i+dataset.temporal_stride]) for i in dataset.pair_starts),'motion_split_disjoint':bool(inp['test_train_motion_disjoint']),'finite_real_batch':all(bool(torch.isfinite(t).all()) for t in tensors),'cuda_not_initialized':not torch.cuda.is_initialized()}
 save('K03/data-audit.json',{'ok':all(checks.values()),'checks':checks,'cpu_only':True,'not_a_training_or_60s_render':True,'model_config':config,'training_frames':dataset.frame_count,'source_clip_ranges':len(dataset.clip_ranges),'adjacent_training_pairs_per_epoch':len(dataset),'selected_batchsize':16,'upstream_train_cli_default_batchsize':8,'batches_per_epoch':(len(dataset)+15)//16,'planned_epochs':60,'batch_tensor_shapes':[list(t.shape) for t in tensors]})
 if not all(checks.values()):raise RuntimeError('A real training batch failed its data audit')
 print('Disjoint real training data and native16-sample CPU batch validated.',flush=True)

if __name__=='__main__':main()
