import json
import os
import time

import torch
from oba import Obj
from tqdm import tqdm
from transformers import get_linear_schedule_with_warmup

from loader.global_setting import Setting
from model_v2.utils.config_manager import ConfigManager, Phases
from task.base_batch import BaseBatch
from task.base_loss import BaseLoss, LossDepot
from utils.config_init import ConfigInit
from utils.gpu import GPU
from utils.logger import Logger
from utils.metrics import MetricPool
from utils.monitor import Monitor
from utils.printer import printer, Color, Printer
from utils.structure import Structure


class Worker:
    def __init__(self, config):
        self.config = config
        self.data, self.model, self.exp = self.config.data, self.config.model, self.config.exp
        self.disable_tqdm = self.exp.policy.disable_tqdm

        Setting.device = self.get_device()

        self.print = printer[('MAIN', '·', Color.CYAN)]
        self.logging = Logger(self.config.data.store.log_file)
        Printer.logger = self.logging
        self.print(json.dumps(Obj.raw(self.config), indent=4))

        self.config_manager = ConfigManager(
            data=self.data,
            model=self.model,
            exp=self.exp,
        )

        self.recommender = self.config_manager.recommender
        self.manager = self.config_manager.manager

    def load(self, path):
        while True:
            self.print(f"load model from exp {path}")
            try:
                state_dict = torch.load(path, map_location=Setting.device)
                break
            except Exception as e:
                if not self.exp.load.wait_load:
                    raise e
                time.sleep(60)

        model_ckpt = state_dict['model']

        self.recommender.load_state_dict(model_ckpt, strict=self.exp.load.strict)
        if not self.exp.load.model_only:
            self.m_optimizer.load_state_dict(state_dict['optimizer'])
            self.m_scheduler.load_state_dict(state_dict['scheduler'])

    def parse_load_path(self):
        if not self.exp.load.save_dir:
            return

        save_dir = os.path.join(self.data.store.save_dir, self.exp.load.save_dir)
        epochs = Obj.raw(self.exp.load.epochs)
        if not epochs:
            epochs = json.load(open(os.path.join(save_dir, 'candidates.json')))
        elif isinstance(epochs, str):
            epochs = eval(epochs)
        assert isinstance(epochs, list), ValueError(f'fail loading epochs: {epochs}')

        return [os.path.join(save_dir, f'epoch_{epoch}.bin') for epoch in epochs]

    def get_device(self):
        cuda = self.config.cuda
        if cuda in ['-1', -1, False]:
            return 'cpu'
        if not cuda:
            return GPU.auto_choose(torch_format=True)
        return f"cuda:{cuda}"

    def log_interval(self, epoch, step, loss: BaseLoss):
        components = [f'step {step}']
        for loss_name, loss_tensor in loss.get_loss_dict().items():
            if loss_name.endswith('loss') and isinstance(loss_tensor, torch.Tensor):
                components.append(f'{loss_name} {loss_tensor.item():.4f}')
        self.print[f'epoch {epoch}'](', '.join(components))

    def log_epoch(self, epoch, loss_depot: LossDepot):
        components = []
        for loss_name, loss_value in loss_depot.table.items():
            components.append(f'{loss_name} {loss_value:.4f}')
        self.print[f'epoch {epoch}'](', '.join(components))

    def train(self):
        monitor = Monitor(
            save_dir=self.data.store.save_dir,
            **Obj.raw(self.exp.store)
        )

        train_steps = len(self.config_manager.sets.train_set) // self.exp.policy.batch_size
        accumulate_step = 0
        accumulate_batch = self.exp.policy.accumulate_batch or 1

        loader = self.config_manager.get_loader(Phases.train).train()
        self.m_optimizer.zero_grad()
        for epoch in range(self.exp.policy.epoch_start, self.exp.policy.epoch + self.exp.policy.epoch_start):
            # loader.start_epoch(epoch - self.exp.policy.epoch_start, self.exp.policy.epoch)
            self.recommender.train()

            for step, batch in enumerate(tqdm(loader, disable=self.disable_tqdm)):  # type: int, BaseBatch
                loss = self.recommender(batch=batch)
                loss.backward()

                accumulate_step += 1
                if accumulate_step == accumulate_batch:
                    self.m_optimizer.step()
                    self.m_scheduler.step()
                    self.m_optimizer.zero_grad()
                    accumulate_step = 0

                if self.exp.policy.check_interval:
                    if self.exp.policy.check_interval < 0:  # step part
                        if (step + 1) % max(train_steps // (-self.exp.policy.check_interval), 1) == 0:
                            self.log_interval(epoch, step, loss)
                    else:
                        if (step + 1) % self.exp.policy.check_interval == 0:
                            self.log_interval(epoch, step, loss)

            loss_depot = self.dev()
            self.log_epoch(epoch, loss_depot)

            state_dict = dict(
                model=self.recommender.state_dict(),
                optimizer=self.m_optimizer.state_dict(),
                scheduler=self.m_scheduler.state_dict(),
            )
            monitor.push(
                epoch=epoch,
                loss=loss_depot.table,
                state_dict=state_dict,
            )

        self.print('Training Ended')
        monitor.export()

    def dev(self, steps=None):
        self.recommender.eval()
        loader = self.config_manager.get_loader(Phases.dev).eval()
        loss_depot = LossDepot()

        for step, batch in enumerate(tqdm(loader, disable=self.disable_tqdm)):
            with torch.no_grad():
                loss = self.recommender(batch=batch)  # [B, neg+1]

            loss_depot.add(loss)

            if steps and step >= steps:
                break

        return loss_depot.summarize()

    def test(self, steps=None):
        label_col = self.data.test.label_col
        group_col = self.data.test.group_col
        pool = MetricPool.parse(self.exp)

        self.recommender.eval()
        loader = self.config_manager.get_loader(Phases.test).test()

        score_series, label_series, group_series = [], [], []
        for step, batch in enumerate(tqdm(loader, disable=self.disable_tqdm)):
            with torch.no_grad():
                task_output = self.recommender(batch=batch)
            labels = batch.append[label_col].tolist()
            groups = batch.append[group_col].tolist()
            scores = self.task.calculate_scores(task_output, batch, model=self.model_container)

            score_series.extend(scores)
            label_series.extend(labels)
            group_series.extend(groups)

            if steps and step >= steps:
                break

        results = pool.calculate(score_series, label_series, group_series)
        for metric in results:
            self.print(f'{metric}: {results[metric]}')

    def train_runner(self):
        self.m_optimizer = torch.optim.Adam(
            params=filter(lambda p: p.requires_grad, self.recommender.parameters()),
            lr=self.exp.policy.lr
        )
        self.m_scheduler = get_linear_schedule_with_warmup(
            self.m_optimizer,
            num_warmup_steps=self.exp.policy.n_warmup,
            num_training_steps=len(self.config_manager.sets.train_set) // self.exp.policy.batch_size * self.exp.policy.epoch,
        )

        self.print('training params')
        total_memory = 0
        for name, p in self.recommender.named_parameters():  # type: str, torch.Tensor
            total_memory += p.element_size() * p.nelement()
            if p.requires_grad:
                self.print(name, p.data.shape)

        if self.load_path:
            self.load(self.load_path[0])
        self.train()

    def dev_runner(self):
        loss_depot = self.dev(10)
        self.log_epoch(0, loss_depot)

    def test_runner(self):
        self.test()

    def iter_runner(self, handler):
        for path in self.load_path:
            self.load(path)
            handler()

    def run(self):
        mode = self.exp.mode.lower()
        if mode == 'train':
            self.train_runner()
        elif mode == 'dev':
            self.iter_runner(self.dev_runner)
        elif self.exp.mode == 'test':
            self.iter_runner(self.test_runner)


if __name__ == '__main__':
    configuration = ConfigInit(
        required_args=['data', 'model', 'exp'],
        makedirs=[
            'data.store.save_dir',
        ]
    ).parse()

    worker = Worker(config=configuration)
    worker.run()