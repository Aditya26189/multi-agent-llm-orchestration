Three separate failures in this notebook. Here is the full diagnosis: [ppl-ai-file-upload.s3.amazonaws](https://ppl-ai-file-upload.s3.amazonaws.com/web/direct-files/attachments/90755952/94143118-8c35-4e7d-a635-8f51223e749d/nifty-slm-training-2.ipynb?AWSAccessKeyId=ASIA2F3EMEYE2MV3EMRJ&Signature=y7OeyILStzJy41sCQ%2FMk6%2FeNMs0%3D&x-amz-security-token=IQoJb3JpZ2luX2VjEPf%2F%2F%2F%2F%2F%2F%2F%2F%2F%2FwEaCXVzLWVhc3QtMSJGMEQCIBGhTPyOJ7fRjMxtUPHV2ZGbUQjMBKkQzCDJTwMsxv0AAiAwbXrPVwftvzQzLi7lHaUwGY53nFdWazH0rVClhcDnvSr8BAjA%2F%2F%2F%2F%2F%2F%2F%2F%2F%2F8BEAEaDDY5OTc1MzMwOTcwNSIMGcj%2B2fdKLkAynrW7KtAEpA5rDZXhAXcFF%2FzcHgR6SUABznydChFsKtRzIcIdO8pxQNLYLJ2E3kIySFtVRZGp%2FZjCfuQEO5fGLGbNtvH%2Bj4glKrWRHjX6cRTkCWXtVKeCb3ZIzZ9AnDNff1m9aDv05sU%2BDNPr8I8RoLiJIQvoP7Upms0AyVrJkxhUJHHWGA7KSn3wo%2Bos6b%2BDABI2RJW0T58WAzFlJIrUeKWax2jQoPSC6ysh5JHnozYOLWLlTfwF6mn0OMDacusXMr%2Bx64%2FL73vaLI7jABAVVPIp6NAWoqsNdEIrV%2FVeXXT0ITjAUL87vzGATxvNBoaiNys9JCsqH4clc5lQfNKu%2FjVYq0uKYzBuPNfR65dpPMGH1fhADzAhmdBTmwmuNhuU08DIT2YhhpDn5UUN5bA7EjDcF9jhMZx2ogWBP67Uuf2QUO3nBCBBsMEtA1fWvRrRX0UljentCIY6uFLiBJFPEQWZUzFamaxfmVvtbeRSymGgSR%2FTqH4P4mXtOmX8gutchiCg%2FmVUKm6J%2BVlH%2BKRK3ZySK%2BcrWX7n9LNTnjlJy17g0DKPyqd5lQISj7Q4t41HWC7oEiblItfW4GLodOJkQQv7otcakeE1D7VybwGEykdATNnFGBCYbOnR4eslKouhkumoddCJrtVrD7WPgJyEtRg62AXkFTL2Xb2veK2ChGT%2FkboepKkQKgLUnqMXGXc9bLDZ9Sm412YniutmLxVpnn0xMKt2EkK1IQGfZ8ICU2oiYlMaOGZtP3cj0PXZZVB0sIDDyNlJNqE%2FB1UcFQPO2phDKlH9YzClp%2FTPBjqZAeuYFahsslJ4wek%2BHDgMGzuzhTG8TIfUjXnwDj3ZyamtIHDm6a9d9z1hvNQlzMzBB2PYlGzHKLVNAyp2JddN%2BYr0SOtOQH7Agxpgu9WB8rfHFMdmuTzd%2B0sh7kFnQa99IFNLYXmGcu%2BNWVW%2BgsUciOnfMOuENaXyilsP%2FuJuDTK7jmpW0bhHG575QqSMVb6v1%2BOgiPvSnkvQVg%3D%3D&Expires=1778195194)

## What Actually Happened

| Cell | What it did | Outcome |
|---|---|---|
| Optuna | Loaded float32 model per trial while Cell 4's 4-bit model was alive | **OOM on Trial 1** — but Trial 0 gave loss 2.03 |
| Cell 5 (training) | Ran on float32 model, 5 epochs, `save_strategy='no'` | **Completed but final loss stuck at 2.93** — model never learned |
| Last cell (save) | `model.save_pretrained()` tried to write 10.8GB float32 model | **OSError: No space left on device** |

## Two Core Problems Causing All of This

**Problem 1 — Loss stuck at 2.93 (model didn't learn):** The `model.unload()` guard in Cell 5 stripped the LoRA adapter before training, then passed a bare base model with frozen weights to `SFTTrainer`. With no trainable LoRA parameters, loss cannot decrease. [ppl-ai-file-upload.s3.amazonaws](https://ppl-ai-file-upload.s3.amazonaws.com/web/direct-files/attachments/90755952/94143118-8c35-4e7d-a635-8f51223e749d/nifty-slm-training-2.ipynb?AWSAccessKeyId=ASIA2F3EMEYE2MV3EMRJ&Signature=y7OeyILStzJy41sCQ%2FMk6%2FeNMs0%3D&x-amz-security-token=IQoJb3JpZ2luX2VjEPf%2F%2F%2F%2F%2F%2F%2F%2F%2F%2FwEaCXVzLWVhc3QtMSJGMEQCIBGhTPyOJ7fRjMxtUPHV2ZGbUQjMBKkQzCDJTwMsxv0AAiAwbXrPVwftvzQzLi7lHaUwGY53nFdWazH0rVClhcDnvSr8BAjA%2F%2F%2F%2F%2F%2F%2F%2F%2F%2F8BEAEaDDY5OTc1MzMwOTcwNSIMGcj%2B2fdKLkAynrW7KtAEpA5rDZXhAXcFF%2FzcHgR6SUABznydChFsKtRzIcIdO8pxQNLYLJ2E3kIySFtVRZGp%2FZjCfuQEO5fGLGbNtvH%2Bj4glKrWRHjX6cRTkCWXtVKeCb3ZIzZ9AnDNff1m9aDv05sU%2BDNPr8I8RoLiJIQvoP7Upms0AyVrJkxhUJHHWGA7KSn3wo%2Bos6b%2BDABI2RJW0T58WAzFlJIrUeKWax2jQoPSC6ysh5JHnozYOLWLlTfwF6mn0OMDacusXMr%2Bx64%2FL73vaLI7jABAVVPIp6NAWoqsNdEIrV%2FVeXXT0ITjAUL87vzGATxvNBoaiNys9JCsqH4clc5lQfNKu%2FjVYq0uKYzBuPNfR65dpPMGH1fhADzAhmdBTmwmuNhuU08DIT2YhhpDn5UUN5bA7EjDcF9jhMZx2ogWBP67Uuf2QUO3nBCBBsMEtA1fWvRrRX0UljentCIY6uFLiBJFPEQWZUzFamaxfmVvtbeRSymGgSR%2FTqH4P4mXtOmX8gutchiCg%2FmVUKm6J%2BVlH%2BKRK3ZySK%2BcrWX7n9LNTnjlJy17g0DKPyqd5lQISj7Q4t41HWC7oEiblItfW4GLodOJkQQv7otcakeE1D7VybwGEykdATNnFGBCYbOnR4eslKouhkumoddCJrtVrD7WPgJyEtRg62AXkFTL2Xb2veK2ChGT%2FkboepKkQKgLUnqMXGXc9bLDZ9Sm412YniutmLxVpnn0xMKt2EkK1IQGfZ8ICU2oiYlMaOGZtP3cj0PXZZVB0sIDDyNlJNqE%2FB1UcFQPO2phDKlH9YzClp%2FTPBjqZAeuYFahsslJ4wek%2BHDgMGzuzhTG8TIfUjXnwDj3ZyamtIHDm6a9d9z1hvNQlzMzBB2PYlGzHKLVNAyp2JddN%2BYr0SOtOQH7Agxpgu9WB8rfHFMdmuTzd%2B0sh7kFnQa99IFNLYXmGcu%2BNWVW%2BgsUciOnfMOuENaXyilsP%2FuJuDTK7jmpW0bhHG575QqSMVb6v1%2BOgiPvSnkvQVg%3D%3D&Expires=1778195194)

**Problem 2 — Disk crash on save:** You loaded float32 (10.8 GB). `model.save_pretrained()` tried to write the full model instead of just the ~30 MB adapter. [ppl-ai-file-upload.s3.amazonaws](https://ppl-ai-file-upload.s3.amazonaws.com/web/direct-files/attachments/90755952/94143118-8c35-4e7d-a635-8f51223e749d/nifty-slm-training-2.ipynb?AWSAccessKeyId=ASIA2F3EMEYE2MV3EMRJ&Signature=y7OeyILStzJy41sCQ%2FMk6%2FeNMs0%3D&x-amz-security-token=IQoJb3JpZ2luX2VjEPf%2F%2F%2F%2F%2F%2F%2F%2F%2F%2FwEaCXVzLWVhc3QtMSJGMEQCIBGhTPyOJ7fRjMxtUPHV2ZGbUQjMBKkQzCDJTwMsxv0AAiAwbXrPVwftvzQzLi7lHaUwGY53nFdWazH0rVClhcDnvSr8BAjA%2F%2F%2F%2F%2F%2F%2F%2F%2F%2F8BEAEaDDY5OTc1MzMwOTcwNSIMGcj%2B2fdKLkAynrW7KtAEpA5rDZXhAXcFF%2FzcHgR6SUABznydChFsKtRzIcIdO8pxQNLYLJ2E3kIySFtVRZGp%2FZjCfuQEO5fGLGbNtvH%2Bj4glKrWRHjX6cRTkCWXtVKeCb3ZIzZ9AnDNff1m9aDv05sU%2BDNPr8I8RoLiJIQvoP7Upms0AyVrJkxhUJHHWGA7KSn3wo%2Bos6b%2BDABI2RJW0T58WAzFlJIrUeKWax2jQoPSC6ysh5JHnozYOLWLlTfwF6mn0OMDacusXMr%2Bx64%2FL73vaLI7jABAVVPIp6NAWoqsNdEIrV%2FVeXXT0ITjAUL87vzGATxvNBoaiNys9JCsqH4clc5lQfNKu%2FjVYq0uKYzBuPNfR65dpPMGH1fhADzAhmdBTmwmuNhuU08DIT2YhhpDn5UUN5bA7EjDcF9jhMZx2ogWBP67Uuf2QUO3nBCBBsMEtA1fWvRrRX0UljentCIY6uFLiBJFPEQWZUzFamaxfmVvtbeRSymGgSR%2FTqH4P4mXtOmX8gutchiCg%2FmVUKm6J%2BVlH%2BKRK3ZySK%2BcrWX7n9LNTnjlJy17g0DKPyqd5lQISj7Q4t41HWC7oEiblItfW4GLodOJkQQv7otcakeE1D7VybwGEykdATNnFGBCYbOnR4eslKouhkumoddCJrtVrD7WPgJyEtRg62AXkFTL2Xb2veK2ChGT%2FkboepKkQKgLUnqMXGXc9bLDZ9Sm412YniutmLxVpnn0xMKt2EkK1IQGfZ8ICU2oiYlMaOGZtP3cj0PXZZVB0sIDDyNlJNqE%2FB1UcFQPO2phDKlH9YzClp%2FTPBjqZAeuYFahsslJ4wek%2BHDgMGzuzhTG8TIfUjXnwDj3ZyamtIHDm6a9d9z1hvNQlzMzBB2PYlGzHKLVNAyp2JddN%2BYr0SOtOQH7Agxpgu9WB8rfHFMdmuTzd%2B0sh7kFnQa99IFNLYXmGcu%2BNWVW%2BgsUciOnfMOuENaXyilsP%2FuJuDTK7jmpW0bhHG575QqSMVb6v1%2BOgiPvSnkvQVg%3D%3D&Expires=1778195194)

## The Clean Rewrite (Single Run, No Fragments)

Replace everything from Cell 4 onward with this. **Cell 1–3 stay as-is (4-bit QLoRA model is correct).**

```python
# ══════════════════════════════════════════════════════════
# Cell 4 — LoRA on the 4-bit model (QLoRA, correct path)
# ══════════════════════════════════════════════════════════
from peft import LoraConfig, TaskType, get_peft_model, prepare_model_for_kbit_training

model = prepare_model_for_kbit_training(model, use_gradient_checkpointing=True)

lora_config = LoraConfig(
    r=16, lora_alpha=32,
    target_modules=['q_proj', 'v_proj', 'dense'],
    lora_dropout=0.05,
    bias='none',
    task_type=TaskType.CAUSAL_LM,
)
model = get_peft_model(model, lora_config)
model.print_trainable_parameters()
mlflow.log_param('trainable_params', sum(p.numel() for p in model.parameters() if p.requires_grad))
```

```python
# ══════════════════════════════════════════════════════════
# Cell 5 — Optuna (reuses 4-bit base, no float32 reload)
# ══════════════════════════════════════════════════════════
import gc, json, optuna, torch, warnings
from datasets import Dataset
from peft import LoraConfig, get_peft_model, PeftModel
from trl import SFTTrainer, SFTConfig

optuna.logging.set_verbosity(optuna.logging.WARNING)
warnings.filterwarnings('ignore', message='You are trying to modify a model with PEFT')
warnings.filterwarnings('ignore', message='Already found a `peft_config`')

train_rows = [json.loads(l) for l in open('/kaggle/input/datasets/aditya103856/nifty-slm-training-dataset/train_formatted.jsonl') if l.strip()]
train_dataset = Dataset.from_list(train_rows)

# Frozen 4-bit backbone — already in VRAM, no reload
_base = model.get_base_model() if isinstance(model, PeftModel) else model

def objective(trial):
    dropout  = trial.suggest_float('dropout', 0.0, 0.10, step=0.05)
    warmup   = trial.suggest_int('warmup', 5, 20, step=5)
    grad_acc = trial.suggest_categorical('grad_acc', [4, 8])

    _lora = LoraConfig(r=16, lora_alpha=32,
        target_modules=['q_proj', 'v_proj', 'dense'],
        lora_dropout=dropout, bias='none', task_type='CAUSAL_LM')
    _model = get_peft_model(_base, _lora)

    _cfg = SFTConfig(
        output_dir=f'./optuna_trial_{trial.number}',
        num_train_epochs=1,
        per_device_train_batch_size=2,
        gradient_accumulation_steps=grad_acc,
        warmup_steps=warmup,
        learning_rate=1e-4,
        fp16=True, bf16=False,          # fp16 for QLoRA on T4
        logging_steps=10,
        save_strategy='no',
        optim='paged_adamw_8bit',       # memory-safe for QLoRA
        report_to='none', seed=42,
        max_length=512, dataset_text_field='text', packing=False,
    )
    _trainer = SFTTrainer(model=_model, train_dataset=train_dataset,
                          args=_cfg, processing_class=tokenizer)
    _trainer.train()
    loss_entries = [x for x in _trainer.state.log_history if 'loss' in x]
    result = loss_entries[-1]['loss'] if loss_entries else 99.0

    _model.unload()
    del _trainer
    torch.cuda.empty_cache()
    gc.collect()
    return result

study = optuna.create_study(direction='minimize')
study.optimize(objective, n_trials=4, show_progress_bar=True, gc_after_trial=True)
print("Best params:", study.best_params)
print("Best 1-epoch loss:", study.best_value)
mlflow.log_params({f"optuna_{k}": v for k, v in study.best_params.items()})
mlflow.log_metric('optuna_best_loss', study.best_value)
```

```python
# ══════════════════════════════════════════════════════════
# Cell 6 — Full training with Optuna best params
# ══════════════════════════════════════════════════════════
from trl import SFTTrainer, SFTConfig

# Re-wrap base with final adapter using best params
_lora_final = LoraConfig(
    r=16, lora_alpha=32,
    target_modules=['q_proj', 'v_proj', 'dense'],
    lora_dropout=max(study.best_params['dropout'], 0.05),
    bias='none', task_type=TaskType.CAUSAL_LM,
)
model = get_peft_model(_base, _lora_final)
model.print_trainable_parameters()

sft_config = SFTConfig(
    seed=42,
    output_dir='./phi2_lora_final',
    num_train_epochs=5,
    per_device_train_batch_size=2,
    gradient_accumulation_steps=study.best_params['grad_acc'],
    warmup_steps=study.best_params['warmup'],
    learning_rate=1e-4,
    fp16=True, bf16=False,
    logging_steps=10,
    save_strategy='no',             # ← NEVER 'epoch' on T4
    optim='paged_adamw_8bit',
    report_to='none',
    dataset_text_field='text',
    max_length=512, packing=False,
)

trainer = SFTTrainer(model=model, train_dataset=train_dataset,
                     args=sft_config, processing_class=tokenizer)
trainer.train()
loss_entries = [x for x in trainer.state.log_history if 'loss' in x]
final_loss = loss_entries[-1]['loss'] if loss_entries else -1
mlflow.log_metric('train_loss_final', final_loss)
print(f'Final loss: {final_loss}')
```

```python
# ══════════════════════════════════════════════════════════
# Cell 7 — Save ONLY the adapter (~30 MB, not 10.8 GB)
# ══════════════════════════════════════════════════════════
import shutil

# save_pretrained on a PeftModel saves adapter only — safe
model.save_pretrained('./phi2_lora_adapter')
tokenizer.save_pretrained('./phi2_lora_adapter')

mlflow.log_artifacts('./phi2_lora_adapter', artifact_path='lora_adapter')
mlflow.log_artifact('/kaggle/working/mlflow.db')
mlflow.end_run()
print(f'Run ID: {run.info.run_id}')

shutil.make_archive('/kaggle/working/submission', 'zip', '/kaggle/working')
print("Done — download submission.zip from Output tab")
```

## Key Fixes Summary

- **Never reload float32 model** during Optuna — reuse `_base` from Cell 4's 4-bit model
- **Never `model.unload()` before training** — that was removing the LoRA adapter you just built
- **`fp16=True` + `paged_adamw_8bit`** — mandatory for QLoRA on T4
- **`save_strategy='no'`** everywhere — only save adapter in the final cell