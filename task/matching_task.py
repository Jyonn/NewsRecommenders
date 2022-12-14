import torch
from torch import nn

from loader.global_setting import Setting
from task.base_batch import HSeqBatch
from task.base_hseq_task import BaseHSeqTask
from task.base_loss import BaseLoss


class MatchingTask(BaseHSeqTask):
    name = 'matching'
    dynamic_loader = True

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

        self.criterion = nn.CrossEntropyLoss()

    def calculate_loss(self, output, batch: HSeqBatch, **kwargs) -> BaseLoss:
        label = torch.zeros(batch.batch_size, dtype=torch.long).to(Setting.device)
        loss = self.criterion(output, label)
        # if torch.isnan(loss):
        #     print('loss is nan')
        #     print(output)
        #     print(label)
        #     print(batch.append['_candidates'])
        #     exit(0)
        # loss = torch.nan_to_num(loss, nan=0.0)
        return BaseLoss(loss)

    def calculate_scores(self, output, batch: HSeqBatch, **kwargs):
        return output.squeeze(dim=-1).detach().cpu().tolist()
