// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import "forge-std/Test.sol";
import "../src/FlashArbitrageReceiver.sol";

contract MockERC20 is IERC20 {
    string public name;
    string public symbol;
    uint8 public decimals = 18;
    mapping(address => uint256) public override balanceOf;
    mapping(address => mapping(address => uint256)) public override allowance;
    uint256 public override totalSupply;

    constructor(string memory _name, string memory _symbol) {
        name = _name;
        symbol = _symbol;
    }

    function mint(address to, uint256 amount) external {
        balanceOf[to] += amount;
        totalSupply += amount;
    }

    function transfer(address recipient, uint256 amount) external override returns (bool) {
        balanceOf[msg.sender] -= amount;
        balanceOf[recipient] += amount;
        return true;
    }

    function approve(address spender, uint256 amount) external override returns (bool) {
        allowance[msg.sender][spender] = amount;
        return true;
    }

    function transferFrom(address sender, address recipient, uint256 amount) external override returns (bool) {
        if (allowance[sender][msg.sender] != type(uint256).max) {
            allowance[sender][msg.sender] -= amount;
        }
        balanceOf[sender] -= amount;
        balanceOf[recipient] += amount;
        return true;
    }
}

contract MockAavePool is IPool {
    uint256 public feeBps = 9; // 0.09% Aave fee

    function flashLoanSimple(
        address receiverAddress,
        address asset,
        uint256 amount,
        bytes calldata params,
        uint16
    ) external override {
        uint256 premium = (amount * feeBps) / 10000;
        
        // Transfer flash loan principal to receiver
        MockERC20(asset).mint(receiverAddress, amount);

        // Execute callback
        bool success = IFlashLoanSimpleReceiver(receiverAddress).executeOperation(
            asset,
            amount,
            premium,
            receiverAddress,
            params
        );
        require(success, "FlashLoan failed");

        // Repay loan + premium
        uint256 amountToRepay = amount + premium;
        MockERC20(asset).transferFrom(receiverAddress, address(this), amountToRepay);
    }
}

contract MockSwapRouter is ISwapRouter {
    uint256 public returnMultiplierBps = 10500; // Simulates 5% gross profit spread

    function setMultiplier(uint256 _multiplier) external {
        returnMultiplierBps = _multiplier;
    }

    function exactInputSingle(ExactInputSingleParams calldata params) external payable override returns (uint256 amountOut) {
        MockERC20(params.tokenIn).transferFrom(msg.sender, address(this), params.amountIn);
        
        // Calculate output with multiplier
        amountOut = (params.amountIn * returnMultiplierBps) / 10000;
        MockERC20(params.tokenOut).mint(params.recipient, amountOut);
    }
}

contract FlashArbitrageTest is Test {
    FlashArbitrageReceiver public receiver;
    MockAavePool public mockAave;
    MockSwapRouter public mockRouter;
    MockERC20 public usdc;
    MockERC20 public weth;

    address public owner = address(0xAA11);

    function setUp() public {
        vm.startPrank(owner);
        mockAave = new MockAavePool();
        mockRouter = new MockSwapRouter();
        usdc = new MockERC20("USD Coin", "USDC");
        weth = new MockERC20("Wrapped Ether", "WETH");

        receiver = new FlashArbitrageReceiver(address(mockAave), address(mockRouter));
        vm.stopPrank();
    }

    function testProfitableFlashArbitrageExecution() public {
        vm.startPrank(owner);

        uint256 borrowAmount = 100_000 * 1e18; // 100,000 USDC Flash Loan
        uint256 minProfit = 100 * 1e18;        // Minimum 100 USDC profit

        bytes memory params = abi.encode(
            address(weth),
            uint24(500),
            uint24(500),
            minProfit
        );

        // Execute flash loan
        receiver.requestFlashLoan(address(usdc), borrowAmount, params);

        uint256 ownerBalance = usdc.balanceOf(owner);
        assertGt(ownerBalance, minProfit, "Owner should receive net profit");
        emit log_named_uint("[+] Net Arbitrage Profit Realized (USDC):", ownerBalance / 1e18);

        vm.stopPrank();
    }

    function testRevertOnUnprofitableArbitrage() public {
        vm.startPrank(owner);

        // Set DEX spread to a loss (99% return = -1% loss)
        mockRouter.setMultiplier(9900);

        uint256 borrowAmount = 100_000 * 1e18;
        uint256 minProfit = 100 * 1e18;

        bytes memory params = abi.encode(
            address(weth),
            uint24(500),
            uint24(500),
            minProfit
        );

        // Should revert atomically to protect user from losing money
        vm.expectRevert();
        receiver.requestFlashLoan(address(usdc), borrowAmount, params);

        vm.stopPrank();
    }
}
