// SPDX-License-Identifier: GPL-2.0
/*
 * ETEK ET7304 USB Type-C TCPC driver
 *
 * Drives the ET7304 Type-C port controller found on the Radxa Cubie A7Z
 * (A733 / sun60iw2).  It rides on the generic tcpci/tcpm core but adds the two
 * things the generic driver lacks for this board:
 *
 *   1. it controls the external VBUS regulator described by the "vbus-supply"
 *      DT property (the A7Z sources VBUS through a GPIO load switch, not
 *      through a TCPC-internal source);
 *   2. it takes the interrupt from the board-specific "et7304,intr_gpio"
 *      property (the bootloader leaves that pin as an output, so the driver
 *      forces it back to input before requesting the IRQ).
 *
 * Without this driver the i2c device never binds, VBUS is never enabled and
 * nothing plugged into the USB-C port (hubs, cameras, ...) enumerates.
 */

#include <linux/gpio.h>
#include <linux/i2c.h>
#include <linux/interrupt.h>
#include <linux/module.h>
#include <linux/of_gpio.h>
#include <linux/regmap.h>
#include <linux/regulator/consumer.h>
#include <linux/usb/tcpm.h>
#include <linux/usb/tcpci.h>

struct et7304_chip {
	struct tcpci_data data;
	struct tcpci *tcpci;
	struct device *dev;
	struct regulator *vbus;
	bool vbus_on;
};

/* Return >0 after handling VBUS ourselves so tcpci_set_vbus() skips the
 * chip-internal POWER_CTRL/COMMAND writes (the ET7304 has no internal source).
 */
static int et7304_set_vbus(struct tcpci *tcpci, struct tcpci_data *data,
			   bool source, bool sink)
{
	struct et7304_chip *chip = container_of(data, struct et7304_chip, data);
	bool on = source || sink;
	int ret;

	if (!chip->vbus)
		return 0;

	if (chip->vbus_on == on)
		return 1;

	if (on)
		ret = regulator_enable(chip->vbus);
	else
		ret = regulator_disable(chip->vbus);
	if (ret < 0) {
		dev_err(chip->dev, "cannot %s vbus regulator, ret=%d\n",
			on ? "enable" : "disable", ret);
		return ret;
	}

	chip->vbus_on = on;
	dev_info(chip->dev, "vbus %s\n", on ? "on" : "off");
	return 1;
}

static irqreturn_t et7304_irq(int irq, void *dev_id)
{
	struct et7304_chip *chip = dev_id;

	return tcpci_irq(chip->tcpci);
}

static int et7304_get_irq(struct et7304_chip *chip)
{
	struct device *dev = chip->dev;
	struct device_node *np = dev->of_node;
	int gpio, irq, ret;

	gpio = of_get_named_gpio(np, "et7304,intr_gpio", 0);
	if (!gpio_is_valid(gpio))
		return 0;

	ret = devm_gpio_request_one(dev, gpio, GPIOF_IN, "et7304-intr");
	if (ret)
		dev_warn(dev, "gpio %d request failed: %d\n", gpio, ret);

	/* The pin may be left as an output by the bootloader; force it back to
	 * input so it can be locked as an IRQ source.
	 */
	gpio_direction_input(gpio);

	irq = gpio_to_irq(gpio);
	if (irq > 0)
		return irq;
	return 0;
}

static const struct regmap_config et7304_regmap_config = {
	.reg_bits = 8,
	.val_bits = 8,
	.max_register = 0xFF,
};

static int et7304_probe(struct i2c_client *client)
{
	struct et7304_chip *chip;
	int err, irq;
	u16 val = 0;

	chip = devm_kzalloc(&client->dev, sizeof(*chip), GFP_KERNEL);
	if (!chip)
		return -ENOMEM;
	chip->dev = &client->dev;

	chip->data.regmap = devm_regmap_init_i2c(client, &et7304_regmap_config);
	if (IS_ERR(chip->data.regmap)) {
		dev_err(chip->dev, "regmap init failed\n");
		return PTR_ERR(chip->data.regmap);
	}
	i2c_set_clientdata(client, chip);

	chip->vbus = devm_regulator_get_optional(chip->dev, "vbus");
	if (IS_ERR(chip->vbus)) {
		if (PTR_ERR(chip->vbus) != -ENODEV)
			return PTR_ERR(chip->vbus);
		chip->vbus = NULL;
		dev_warn(chip->dev, "no vbus regulator\n");
	} else {
		chip->data.set_vbus = et7304_set_vbus;
	}

	/* Disable chip interrupts before requesting the IRQ. */
	err = regmap_raw_write(chip->data.regmap, TCPC_ALERT_MASK, &val,
			       sizeof(u16));
	if (err < 0)
		return err;

	chip->tcpci = tcpci_register_port(chip->dev, &chip->data);
	if (IS_ERR(chip->tcpci)) {
		dev_err(chip->dev, "tcpci_register_port failed\n");
		return PTR_ERR(chip->tcpci);
	}

	irq = client->irq;
	if (!irq)
		irq = et7304_get_irq(chip);

	if (irq > 0) {
		client->irq = irq;
		err = devm_request_threaded_irq(chip->dev, irq, NULL, et7304_irq,
					IRQF_SHARED | IRQF_ONESHOT | IRQF_TRIGGER_LOW,
					dev_name(chip->dev), chip);
		if (err < 0) {
			dev_err(chip->dev, "request irq %d failed, ret=%d\n", irq, err);
			tcpci_unregister_port(chip->tcpci);
			return err;
		}
	} else {
		dev_warn(chip->dev, "no IRQ; port will not report CC/alert events\n");
	}

	dev_info(chip->dev, "ET7304 Type-C TCPC registered\n");
	return 0;
}

static void et7304_remove(struct i2c_client *client)
{
	struct et7304_chip *chip = i2c_get_clientdata(client);

	if (!IS_ERR_OR_NULL(chip->tcpci))
		tcpci_unregister_port(chip->tcpci);
}

static const struct i2c_device_id et7304_id[] = {
	{ "et7304", 0 },
	{ }
};
MODULE_DEVICE_TABLE(i2c, et7304_id);

static const struct of_device_id et7304_of_match[] = {
	{ .compatible = "etek,et7304" },
	{ }
};
MODULE_DEVICE_TABLE(of, et7304_of_match);

static struct i2c_driver et7304_i2c_driver = {
	.driver = {
		.name = "et7304",
		.of_match_table = et7304_of_match,
	},
	.probe = et7304_probe,
	.remove = et7304_remove,
	.id_table = et7304_id,
};
module_i2c_driver(et7304_i2c_driver);

MODULE_DESCRIPTION("ETEK ET7304 Type-C TCPC driver");
MODULE_LICENSE("GPL");
MODULE_ALIAS("i2c:et7304");