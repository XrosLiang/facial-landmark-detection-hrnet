"""The training script for HRNet facial landmark detection.
"""
import os
from argparse import ArgumentParser

import tensorflow as tf
from tensorflow import keras

from dataset import make_wflw_dataset
from network import hrnet_v2

parser = ArgumentParser()
parser.add_argument("--epochs", default=60, type=int,
                    help="Number of training epochs.")
parser.add_argument("--initial_epoch", default=0, type=int,
                    help="From which epochs to resume training.")
parser.add_argument("--batch_size", default=32, type=int,
                    help="Training batch size.")
parser.add_argument("--export_only", default=False, type=bool,
                    help="Save the model without training.")
parser.add_argument("--eval_only", default=False, type=bool,
                    help="Evaluate the model without training.")
args = parser.parse_args()


class EpochBasedLearningRateSchedule(keras.callbacks.Callback):
    """Sets the learning rate according to epoch schedule."""

    def __init__(self, schedule):
        """
        Args:
            schedule: a tuple that takes an epoch index (integer, indexed from 0)
            and current learning rate.
        """
        super(EpochBasedLearningRateSchedule, self).__init__()
        self.schedule = schedule

    def on_epoch_begin(self, epoch, logs=None):
        if not hasattr(self.model.optimizer, "lr"):
            raise ValueError('Optimizer must have a "lr" attribute.')

        # Get the current learning rate from model's optimizer.
        lr = float(tf.keras.backend.get_value(
            self.model.optimizer.learning_rate))

        # Get the scheduled learning rate.
        def _lr_schedule(epoch, lr, schedule):
            """Helper function to retrieve the scheduled learning rate based on
             epoch."""
            if epoch < schedule[0][0] or epoch > schedule[-1][0]:
                return lr
            for i in range(len(schedule)):
                if epoch == schedule[i][0]:
                    return schedule[i][1]
            return lr

        scheduled_lr = _lr_schedule(epoch, lr, self.schedule)

        # Set the value back to the optimizer before this epoch starts
        tf.keras.backend.set_value(self.model.optimizer.lr, scheduled_lr)
        print("\nEpoch %05d: Learning rate is %6.6f." % (epoch, scheduled_lr))


if __name__ == "__main__":
    # Deep neural network training is complicated. The first thing is making
    # sure you have everything ready for training, like datasets, checkpoints,
    # logs, etc. Modify these paths to suit your needs.

    # Datasets
    train_files_dir = "/home/robin/data/facial-marks/wflw_cropped/train"
    test_files_dir = "/home/robin/data/facial-marks/wflw_cropped/test"

    # Checkpoint is used to resume training.
    checkpoint_dir = "./checkpoints"

    # Save the model for inference later.
    export_dir = "./exported"

    # Log directory will keep training logs like loss/accuracy curves.
    log_dir = "./logs"

    # All sets. Now it's time to build the model. This model is defined in the
    # `network` module with TensorFlow's functional API.
    model = hrnet_v2(input_shape=(256, 256, 3), width=18, output_channels=98)

    # Compile the model and print the model summary.
    model.compile(optimizer=keras.optimizers.Adam(0.0001),
                  loss=keras.losses.MeanSquaredError(),
                  metrics=[keras.metrics.MeanSquaredError()])
    # model.summary()

    # Model built. Restore the latest model if checkpoints are available.
    if not os.path.exists(checkpoint_dir):
        os.makedirs(checkpoint_dir)
        print("Checkpoint directory created: {}".format(checkpoint_dir))

    latest_checkpoint = tf.train.latest_checkpoint(checkpoint_dir)
    if latest_checkpoint:
        print("Checkpoint found: {}, restoring..".format(latest_checkpoint))
        model.load_weights(latest_checkpoint)
        print("Checkpoint restored: {}".format(latest_checkpoint))
    else:
        print("Checkpoint not found. Model weights will be initialized randomly.")

    # If the restored model is ready for inference, save it and quit training.
    if args.export_only:
        if latest_checkpoint is None:
            print("Warning: Model not restored from any checkpoint.")
        model.save(export_dir)
        print("Model saved at: {}".format(export_dir))
        quit()

    # Construct a dataset for evaluation.
    dataset_test = make_wflw_dataset(test_files_dir, "wflw_test",
                                     training=False,
                                     batch_size=args.batch_size,
                                     mode="generator")
    if not isinstance(dataset_test, keras.utils.Sequence):
        dataset_test = dataset_test.batch(
            args.batch_size).prefetch(tf.data.experimental.AUTOTUNE)

    # If only evaluation is required.
    if args.eval_only:
        model.evaluate(dataset_test)
        quit()

    # Construct dataset for validation. The loss value from this dataset will be
    # used to decide which checkpoint should be preserved.
    dataset_val = make_wflw_dataset(test_files_dir, "wflw_test",
                                    training=False,
                                    batch_size=args.batch_size,
                                    mode="generator").take(320)
    if not isinstance(dataset_val, keras.utils.Sequence):
        dataset_val = dataset_val.batch(args.batch_size).prefetch(
            tf.data.experimental.AUTOTUNE)

    # Finally, it's time to train the model.

    # Set hyper parameters for training.
    epochs = args.epochs
    batch_size = args.batch_size

    # Schedule the learning rate with (epoch to start, learning rate) tuples
    schedule = [(1, 0.001),
                (30, 0.0001),
                (50, 0.00001)]

    # All done. The following code will setup and start the trainign.

    # Save a checkpoint. This could be used to resume training.
    checkpoint_path = os.path.join(checkpoint_dir, "hrnetv2")
    callback_checkpoint = keras.callbacks.ModelCheckpoint(
        filepath=checkpoint_path,
        save_weights_only=True,
        verbose=1,
        save_best_only=True)

    # Visualization in TensorBoard
    callback_tensorboard = keras.callbacks.TensorBoard(log_dir=log_dir,
                                                       histogram_freq=1024,
                                                       write_graph=True,
                                                       update_freq='epoch')
    # Learning rate decay.
    callback_lr = EpochBasedLearningRateSchedule(schedule)

    # List all the callbacks.
    callbacks = [callback_checkpoint, callback_tensorboard, callback_lr]

    # Construct training datasets.
    dataset_train = make_wflw_dataset(train_files_dir, "wflw_train",
                                      training=True,
                                      batch_size=batch_size,
                                      mode="generator")
    if not isinstance(dataset_train, keras.utils.Sequence):
        dataset_train = dataset_train.shuffle(1024).batch(
            batch_size).prefetch(tf.data.experimental.AUTOTUNE)

    # Start training loop.
    model.fit(dataset_train, validation_data=dataset_val,
              epochs=epochs, callbacks=callbacks,
              initial_epoch=args.initial_epoch)

    # Make a full evaluation after training.
    model.evaluate(dataset_test)
